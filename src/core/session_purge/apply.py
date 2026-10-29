
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import structlog

from src.core.json_artifact import atomic_write_json
from src.core.inventory import db_trace, file_trace, side_trace
from src.core.inventory.model import Artifact
from src.core.session_purge.model import RECEIPTS_DIR_NAME, PurgeBusy, PurgePlan, PurgeRefused
from src.core.session_purge.plan import acting_material, require_quoted

logger = structlog.get_logger()

_lock = threading.Lock()


@contextmanager
def one_purge_at_a_time() -> Iterator[None]:
    if not _lock.acquire(blocking=False):
        raise PurgeBusy("another purge is running; try again when it finishes")
    try:
        yield
    finally:
        _lock.release()


def check_gates(plan: PurgePlan, *, beast_armed: bool, quoted: Optional[str], typed: Optional[str]) -> None:
    if not beast_armed:
        raise PurgeRefused(403, "Beast Mode is not armed: arm it in the app first, then approve the purge")
    require_quoted(plan, quoted)
    if not plan.ok:
        raise PurgeRefused(409, "purge refused: " + "; ".join(plan.blockers))
    if typed is None or typed != plan.session.display_name:
        raise PurgeRefused(422, "the typed confirmation does not match the session's name exactly; nothing was done")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def receipt_path(state_dir: Path, plan: PurgePlan) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return Path(state_dir) / RECEIPTS_DIR_NAME / f"{stamp}-{plan.session.session_uuid}.json"


def _write_receipt(path: Path, plan: PurgePlan, status: str, started: str,
                   outcomes: Optional[List[Dict[str, Any]]] = None) -> None:
    body = {"schema": 1, "status": status, "started_at": started, "updated_at": _now(),
            "session": plan.session.as_dict(), "fingerprint": plan.fingerprint, "complete": plan.complete,
            "artifacts": outcomes if outcomes is not None else [a.as_dict() for a in plan.artifacts]}
    if not atomic_write_json(path, body, log_event="session_purge_receipt_write_failed"):
        raise OSError(f"the purge receipt could not be written at {path}")


def _outcome(art: Artifact, status: str, removed: int = 0, error: str = "") -> Dict[str, Any]:
    out = {**art.as_dict(), "status": status, "removed": removed}
    if error:
        out["error"] = error
    return out


def _db_phase(conn: sqlite3.Connection, plan: PurgePlan, db_arts: List[Artifact]) -> List[Dict[str, Any]]:
    from src.core import db
    from src.core.inventory import identity

    with db.transaction(conn):
        fresh, _blockers = db_trace.trace(conn, plan.session, plan.shared_with,
                                          identity.other_rows_named(conn, plan.session))
        if acting_material(fresh) != acting_material(db_arts):
            raise PurgeRefused(412, "the session's database rows changed since the plan; read the new plan")
        bodies = next((a for a in fresh if a.op.get("fn") == "exclusive_bodies" and a.action == "delete"), None)
        bodies_op = {"ids": db_trace.exclusive_bodies(conn, bodies.op["transcripts"])} if bodies else None
        outcomes = []
        for art in fresh:
            if art.action != "delete":
                outcomes.append(_outcome(art, art.action))
                continue
            removed = db_trace.delete(conn, art, bodies_op=bodies_op if art is bodies else None)
            outcomes.append(_outcome(art, "deleted", removed))
    return outcomes


def apply_plan(conn: sqlite3.Connection, plan: PurgePlan, *, state_dir: Path) -> Dict[str, Any]:
    started = _now()
    receipt = receipt_path(state_dir, plan)
    _write_receipt(receipt, plan, "started", started)
    db_arts = [a for a in plan.artifacts if a.store == db_trace.STORE]
    rest = [a for a in plan.artifacts if a.store != db_trace.STORE]
    try:
        outcomes = _db_phase(conn, plan, db_arts)
    except (PurgeRefused, sqlite3.Error) as exc:
        _write_receipt(receipt, plan, "failed", started,
                       [_outcome(a, "not_run", error=type(exc).__name__) for a in plan.artifacts])
        logger.error("session_purge_db_failed", session_uuid=plan.session.session_uuid, error=str(exc))
        raise
    for art in rest:
        if art.action != "delete":
            outcomes.append(_outcome(art, art.action))
            continue
        try:
            if art.kind in ("file", "dir"):
                file_trace.delete(art)
                removed = art.count
            else:
                removed = side_trace.delete(art, plan.session)
            outcomes.append(_outcome(art, "deleted", removed))
        except (OSError, ValueError, sqlite3.Error, KeyError) as exc:
            logger.error("session_purge_artifact_failed", session_uuid=plan.session.session_uuid,
                         store=art.store, what=art.what, error=f"{type(exc).__name__}: {exc}")
            outcomes.append(_outcome(art, "failed", error=f"{type(exc).__name__}: {exc}"))
    failed = [o for o in outcomes if o["status"] == "failed"]
    status = "partial" if failed else "done"
    _write_receipt(receipt, plan, status, started, outcomes)
    removed = sum(o["removed"] for o in outcomes if o["status"] == "deleted")
    logger.info("session_purged", session_uuid=plan.session.session_uuid, row_id=plan.session.row_id,
                status=status, artifacts=len(outcomes), removed=removed, failed=len(failed),
                complete=plan.complete, receipt=str(receipt))
    return {"receipt": str(receipt), "status": status, "artifacts": outcomes, "removed": removed,
            "failed": len(failed)}
