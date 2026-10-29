#!/usr/bin/env python3
"""Baseline and verify a CloudeCode upgrade, with three outcomes per check.

THE OUTCOME MODEL, WHICH IS THE POINT OF THE FILE. Every check reports
PASS, FAIL, or CANNOT DETERMINE, and the third never collapses into
either of the others. ``src/core/db.py::get_schema_version`` documents
what that collapse already cost this project once: it folds "no version
recorded" and "a version that will not parse" onto the same ``0``, and a
populated nine-project database migrated with zero backups because a
gate read that ``0`` as a measurement.

Read-only by construction. The database is opened with
``PRAGMA query_only=ON``, which forbids every content write while still
letting a WAL reader create the ``-shm`` index it legitimately needs -
a ``mode=ro`` URI cannot promise the second half.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PASS = "pass"
FAIL = "fail"
UNKNOWN = "cannot-determine"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _install_dir() -> Path:
    env = os.environ.get("CLOUDE_BASELINE_INSTALL_DIR") or ""
    return Path(env) if env else Path(__file__).resolve().parents[1]


def _state_dir(install: Path) -> Tuple[Optional[Path], str]:
    """Resolve the state directory holding cloude.db.

    Description: asks the APPLICATION to resolve it rather than restating
      the precedence here, so this script cannot drift from the thing it
      is checking. Falls back to the documented macOS default only when
      the app will not import, and says which it used.
    Inputs: install (Path) - the checkout.
    Output: (Path | None, str) - the directory and how it was resolved.
    """
    override = os.environ.get("CLOUDE_BASELINE_STATE_DIR") or ""
    if override:
        return Path(override).expanduser(), "explicit --state-dir"

    import contextlib
    import io

    sys.path.insert(0, str(install))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            from src.config import settings  # noqa: E402

            resolved = Path(settings.get_state_dir())
        return resolved, "resolved by src.config.settings"
    except BaseException as exc:  # noqa: BLE001
        why = f"{type(exc).__name__}: {exc}".strip().splitlines()[0][:120]
        default = Path.home() / "Library" / "Application Support" / "CloudeCode"
        if default.exists():
            return default, f"documented default (src.config unavailable, {why})"
        return None, f"UNRESOLVED (src.config unavailable, {why})"


def _read_schema_version(conn: sqlite3.Connection) -> Dict[str, Any]:
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key=?", ("schema_version",)
        ).fetchone()
    except sqlite3.Error as exc:
        return {"outcome": UNKNOWN, "detail": f"meta unreadable: {exc}"}
    if row is None:
        return {"outcome": UNKNOWN, "detail": "no schema_version row in meta"}
    raw = str(row[0])
    try:
        return {"outcome": PASS, "value": int(raw.strip()), "raw": raw}
    except (TypeError, ValueError):
        return {"outcome": UNKNOWN, "detail": f"unparseable schema_version: {raw!r}"}


def _row_counts(conn: sqlite3.Connection) -> Dict[str, Any]:
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
    except sqlite3.Error as exc:
        return {"error": f"could not list tables: {exc}"}
    counts: Dict[str, Any] = {}
    for name in names:
        try:
            counts[name] = int(
                conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            )
        except sqlite3.Error as exc:
            counts[name] = f"ERROR: {exc}"
    return counts


def _session_import_status(conn: sqlite3.Connection) -> Dict[str, Any]:
    try:
        meta = dict(
            conn.execute("SELECT key, value FROM meta").fetchall()
        )
    except sqlite3.Error as exc:
        return {"error": f"meta unreadable: {exc}"}
    at = meta.get("imported_from_json_at")
    detail: Dict[str, Any] = {}
    try:
        blob = json.loads(meta.get("imported_from_json_result") or "{}")
        detail = blob.get("sessions_import_detail") or {}
    except ValueError:
        detail = {}
    return {
        "ran": bool(at),
        "at": at,
        "imported": detail.get("sessions_imported"),
        "listing_reason": detail.get("listing_reason"),
        "pending_reason": meta.get("session_import_pending_reason"),
    }


def _trail_tail(conn: sqlite3.Connection, limit: int = 5) -> Any:
    try:
        rows = conn.execute(
            "SELECT kind, from_version, to_version, status, started_at "
            "FROM migration_trail ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    return [
        {
            "kind": r[0],
            "from_version": r[1],
            "to_version": r[2],
            "status": r[3],
            "started_at": r[4],
        }
        for r in rows
    ]


def _git_version(install: Path) -> str:
    for args in (["describe", "--tags", "--exact-match"], ["rev-parse", "--short", "HEAD"]):
        try:
            out = subprocess.run(
                ["git", "-C", str(install)] + args,
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return "UNKNOWN"


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.execute("PRAGMA query_only=ON")
    return conn


def _snapshot() -> Dict[str, Any]:
    install = _install_dir()
    state, how = _state_dir(install)
    snap: Dict[str, Any] = {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "install_dir": str(install),
        "state_dir": str(state) if state else None,
        "state_dir_resolution": how,
        "version": _git_version(install),
    }
    if state is None:
        snap["database"] = {"outcome": UNKNOWN, "detail": "state dir unresolved"}
        return snap
    try:
        from src.core.db import db_path_for  # noqa: E402,PLC0415

        db_path = db_path_for(state)
    except Exception:
        db_path = state / "carnivore.db"
    if not db_path.exists() or db_path.stat().st_size == 0:
        for name in ("carnivore.db", "cloude.db"):
            if (state / name).exists() and (state / name).stat().st_size > 0:
                db_path = state / name
                break
    if not db_path.exists():
        snap["database"] = {"outcome": UNKNOWN, "detail": f"no database at {db_path}"}
        return snap
    try:
        conn = _open_readonly(db_path)
    except sqlite3.Error as exc:
        snap["database"] = {"outcome": UNKNOWN, "detail": f"could not open: {exc}"}
        return snap
    try:
        snap["database"] = {
            "outcome": PASS,
            "path": str(db_path),
            "schema_version": _read_schema_version(conn),
            "row_counts": _row_counts(conn),
            "session_import": _session_import_status(conn),
            "migration_trail_tail": _trail_tail(conn),
        }
    finally:
        conn.close()
    return snap


def cmd_baseline() -> int:
    """Write a pre-upgrade baseline. Exit 2 when it is not usable."""
    snap = _snapshot()
    out_dir = Path(os.environ.get("CLOUDE_BASELINE_OUT_DIR") or ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_utc_stamp()}.json"
    path.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n")
    print(json.dumps(snap, indent=2, sort_keys=True))
    print(f"\nbaseline written: {path}")
    db = snap.get("database", {})
    if db.get("outcome") != PASS:
        print(
            "\nCANNOT DETERMINE: no usable database baseline "
            f"({db.get('detail')}). Do NOT start an upgrade you will not be "
            "able to verify.",
            file=sys.stderr,
        )
        return 2
    return 0


def _newest_baseline(out_dir: Path) -> Optional[Path]:
    named = os.environ.get("CLOUDE_BASELINE_FILE") or ""
    if named:
        p = Path(named)
        return p if p.exists() else None
    if not out_dir.exists():
        return None
    files = sorted(out_dir.glob("*.json"))
    return files[-1] if files else None


def _served_version(url: str) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{url}/api/v1/health", timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return {"outcome": PASS, "version": body.get("version"), "body": body}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return {"outcome": UNKNOWN, "detail": f"server not answering at {url}: {exc}"}


def _trail_verdict(status: str, install: Path) -> str:
    sys.path.insert(0, str(install))
    try:
        from src.core.db_models import (  # noqa: E402
            TRAIL_STATUS_COMPLETED,
            TRAIL_STATUS_COMPLETED_AFTER_INTERRUPT,
            TRAIL_STATUS_FAILED,
            TRAIL_STATUS_INTERRUPTED,
            TRAIL_STATUS_STARTED,
        )
    except BaseException:  # noqa: BLE001
        return UNKNOWN
    if status in (TRAIL_STATUS_COMPLETED, TRAIL_STATUS_COMPLETED_AFTER_INTERRUPT):
        return PASS
    if status in (TRAIL_STATUS_FAILED, TRAIL_STATUS_INTERRUPTED):
        return FAIL
    if status == TRAIL_STATUS_STARTED:
        return UNKNOWN
    return UNKNOWN


def _emit(results: List[Tuple[str, str, str]]) -> int:
    width = max(len(name) for name, _, _ in results)
    for name, outcome, detail in results:
        print(f"{name.ljust(width)}  {outcome.upper():<17} {detail}")
    if any(o == FAIL for _, o, _ in results):
        return 1
    if any(o == UNKNOWN for _, o, _ in results):
        return 2
    return 0


def cmd_verify() -> int:
    install = _install_dir()
    out_dir = Path(os.environ.get("CLOUDE_BASELINE_OUT_DIR") or ".")
    base_path = _newest_baseline(out_dir)
    results: List[Tuple[str, str, str]] = []

    if base_path is None:
        print(
            "CANNOT DETERMINE: no baseline found. Nothing to compare against, "
            "so this upgrade cannot be verified. Take a baseline BEFORE the "
            "next one.",
            file=sys.stderr,
        )
        return 2

    before = json.loads(base_path.read_text())
    now = _snapshot()
    print(f"baseline: {base_path}\n")

    results.append((
        "version",
        PASS if now["version"] != "UNKNOWN" else UNKNOWN,
        f"{before.get('version')} -> {now.get('version')}",
    ))

    db_before = before.get("database", {})
    db_now = now.get("database", {})
    if db_before.get("outcome") != PASS or db_now.get("outcome") != PASS:
        results.append((
            "database", UNKNOWN,
            f"before={db_before.get('outcome')} now={db_now.get('outcome')} "
            f"({db_now.get('detail') or db_before.get('detail')})",
        ))
        return _emit(results)

    sv_b, sv_n = db_before["schema_version"], db_now["schema_version"]
    if sv_b.get("outcome") != PASS or sv_n.get("outcome") != PASS:
        results.append((
            "schema version", UNKNOWN,
            f"before={sv_b.get('outcome')} now={sv_n.get('outcome')}: "
            f"{sv_n.get('detail') or sv_b.get('detail')}",
        ))
    elif sv_n["value"] < sv_b["value"]:
        results.append((
            "schema version", FAIL,
            f"WENT BACKWARDS: {sv_b['value']} -> {sv_n['value']}",
        ))
    else:
        moved = "no migration on this path" if sv_n["value"] == sv_b["value"] else "migrated"
        results.append((
            "schema version", PASS,
            f"{sv_b['value']} -> {sv_n['value']} ({moved})",
        ))

    rc_b, rc_n = db_before["row_counts"], db_now["row_counts"]
    if "error" in rc_b or "error" in rc_n:
        results.append(("row counts", UNKNOWN, "table list unreadable on one side"))
    else:
        lost, missing, changed = [], [], []
        for table, count in rc_b.items():
            if table not in rc_n:
                missing.append(table)
                continue
            if isinstance(count, int) and isinstance(rc_n[table], int):
                if rc_n[table] < count:
                    lost.append(f"{table} {count}->{rc_n[table]}")
                elif rc_n[table] != count:
                    changed.append(f"{table} {count}->{rc_n[table]}")
            else:
                missing.append(table)
        if lost:
            results.append(("row counts", FAIL, "ROWS LOST: " + ", ".join(lost)))
        elif missing:
            results.append((
                "row counts", UNKNOWN,
                "table absent or uncountable on one side: " + ", ".join(missing),
            ))
        else:
            detail = "no table lost rows"
            if changed:
                detail += "; grew: " + ", ".join(changed)
            results.append(("row counts", PASS, detail))

    imp = db_now.get("session_import")
    if not isinstance(imp, dict) or "error" in (imp or {}):
        results.append((
            "session import", UNKNOWN,
            (imp or {}).get("error", "not recorded in this snapshot - "
                            "the baseline predates this check"),
        ))
    elif imp.get("pending_reason"):
        results.append((
            "session import", UNKNOWN,
            f"has not run yet: {imp['pending_reason']}. It retries on the "
            "next start; existing sessions are NOT imported until it does",
        ))
    elif not imp.get("ran"):
        results.append((
            "session import", UNKNOWN,
            "no import record at all - either this install predates the "
            "import or it has never completed a start with a readable "
            "datastore",
        ))
    else:
        n = imp.get("imported")
        reason = imp.get("listing_reason")
        if reason == "no_server":
            results.append((
                "session import", PASS,
                "ran; imported 0 because no tmux server was running - a "
                "real answer of zero, not a failed probe",
            ))
        else:
            results.append((
                "session import", PASS,
                f"ran at {imp.get('at')}; imported {n} session(s)"
                + (f" (listing: {reason})" if reason else ""),
            ))

    tail = db_now.get("migration_trail_tail")
    if isinstance(tail, dict) or not tail:
        results.append(("migration trail", UNKNOWN, "no trail entries readable"))
    else:
        newest = tail[0]
        status = str(newest.get("status", "")).lower()
        desc = (
            f"kind={newest.get('kind')} from={newest.get('from_version')} "
            f"to={newest.get('to_version')} status={newest.get('status')}"
        )
        results.append(("migration trail", _trail_verdict(status, install), desc))

    served = _served_version(os.environ.get("CLOUDE_BASELINE_URL") or "http://127.0.0.1:8000")
    if served["outcome"] != PASS:
        results.append(("served version", UNKNOWN, served["detail"]))
    else:
        sv = served.get("version")
        on_disk = now.get("version", "").lstrip("v")
        results.append((
            "served version",
            PASS if sv and on_disk and str(sv).lstrip("v") == on_disk else UNKNOWN,
            f"server reports {sv!r}, checkout is {now.get('version')!r}",
        ))

    return _emit(results)


def main(argv: List[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("baseline", "verify"):
        print("usage: upgrade_snapshot.py {baseline|verify}", file=sys.stderr)
        return 64
    return cmd_baseline() if argv[1] == "baseline" else cmd_verify()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
