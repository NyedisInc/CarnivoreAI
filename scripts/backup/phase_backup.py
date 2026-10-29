#!/usr/bin/env python3
"""Pinned per-phase backup of the critical data, for both Macs (issue #1711, phase P0).

    venv/bin/python3 scripts/backup/phase_backup.py take P1            # before the install of phase P1
    venv/bin/python3 scripts/backup/phase_backup.py verify phase-P1-pre-20261016T120000Z
    venv/bin/python3 scripts/backup/phase_backup.py list
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import structlog  # noqa: E402

from scripts.backup import targets  # noqa: E402
from scripts.backup.db_snapshot import copy_database  # noqa: E402
from scripts.backup.errors import NotEnoughSpace, PhaseBackupError, SetUnreadable  # noqa: E402
from scripts.backup.file_snapshot import copy_file, copy_tree, iter_files  # noqa: E402
from scripts.backup.verify_set import load_manifest, verify_set  # noqa: E402
from src.core.test_write_guard import assert_test_write_allowed  # noqa: E402

logger = structlog.get_logger()
_SPACE_MARGIN = 1.15


def _by_name(state_dir: Path, name: str) -> Optional[Path]:
    target = next((t for t in targets.DB_TARGETS if t.name == name), None)
    return targets.resolve_database(state_dir, target) if target else None


def _source_bytes(dbs: Dict[str, Path], files: Dict[str, Path], trees: Dict[str, Path]) -> int:
    total = sum(p.stat().st_size for p in [*dbs.values(), *files.values()])
    return total + sum(p.stat().st_size for root in trees.values() for _rel, p in iter_files(root))


def _gather(state_dir: Path, config_files: List[Path]) -> Dict[str, Any]:
    dbs: Dict[str, Path] = {}
    absent: List[str] = []
    for target in targets.DB_TARGETS:
        found = targets.resolve_database(state_dir, target)
        if found:
            dbs[target.name] = found
        else:
            absent.append(target.name)
    files = {rel: (state_dir / rel, "state") for rel in targets.STATE_FILES if (state_dir / rel).is_file()}
    files.update({p.name: (p, "abs") for p in config_files if p.is_file()})
    absent += [rel for rel in targets.STATE_FILES if rel not in files]
    trees = {rel: state_dir / rel for rel in targets.STATE_TREES if (state_dir / rel).is_dir()}
    return {"dbs": dbs, "files": files, "trees": trees, "absent": absent}


def take(phase: str, state_dir: Path, dest: Path, config_files: List[Path], now: Optional[datetime] = None) -> Path:
    targets.validate_phase_id(phase)
    found = _gather(state_dir, config_files)
    needed = int(_source_bytes(found["dbs"], {k: v[0] for k, v in found["files"].items()}, found["trees"]) * _SPACE_MARGIN)
    if shutil.disk_usage(dest).free < needed:
        raise NotEnoughSpace(f"{dest} has {shutil.disk_usage(dest).free} bytes free, the set needs about {needed}")
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    final = dest / f"{targets.SET_PREFIX}{phase}-pre-{stamp}"
    assert_test_write_allowed(final)
    if final.exists():
        raise PhaseBackupError(f"{final} already exists")
    partial = dest / f".{final.name}.partial"
    try:
        (partial / "db").mkdir(parents=True)
        manifest = _build_manifest(phase, stamp, state_dir, found, partial)
        _write_manifest(partial, manifest)
        os.rename(partial, final)
    except (PhaseBackupError, OSError):
        if partial.exists():
            partial.rename(dest / f"{final.name}.failed")
        raise
    logger.info("phase_backup_taken", phase=phase, path=str(final), databases=list(manifest["databases"]))
    return final


def _build_manifest(phase: str, stamp: str, state_dir: Path, found: Dict[str, Any], partial: Path) -> Dict[str, Any]:
    databases = {name: {"source": str(src), "copy": f"db/{name}", **copy_database(src, partial / "db" / name)}
                 for name, src in found["dbs"].items()}
    files = {}
    for key, (src, base) in found["files"].items():
        rel = f"files/{'state/' + key if base == 'state' else 'config/' + key}"
        files[key] = {"source": str(src), "base": base, "copy": rel, **copy_file(src, partial / rel)}
    trees = {rel: {"source": str(src), "files": copy_tree(src, partial / "files" / rel)} for rel, src in found["trees"].items()}
    return {"format": targets.MANIFEST_FORMAT, "phase": phase, "created_utc": stamp, "host": socket.gethostname(),
            "state_dir": str(state_dir), "databases": databases, "files": files, "trees": trees, "absent": found["absent"]}


def _write_manifest(partial: Path, manifest: Dict[str, Any]) -> None:
    path = partial / targets.MANIFEST_NAME
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def candidate_destinations(dest: Optional[str], state_dir: Path) -> List[Path]:
    if dest:
        return [Path(dest).expanduser()]
    return [targets.BACKUP_VOLUME, state_dir / targets.FALLBACK_DIR_NAME]


def list_sets(folders: List[Path]) -> List[Dict[str, Any]]:
    out = []
    for folder in folders:
        for path in sorted(folder.glob(f"{targets.SET_PREFIX}*-pre-*")) if folder.is_dir() else []:
            if path.suffix in (".failed", ".partial") or not path.is_dir():
                continue
            try:
                m = load_manifest(path)
                rows = sum(t.get("rows", 0) for d in m["databases"].values() for t in d["tables"].values())
                out.append({"name": path.name, "path": str(path), "phase": m["phase"], "created_utc": m["created_utc"],
                            "databases": sorted(m["databases"]), "rows": rows, "readable": True})
            except SetUnreadable:
                out.append({"name": path.name, "path": str(path), "readable": False})
    return sorted(out, key=lambda s: s["name"].rsplit("-pre-", 1)[-1], reverse=True)


def _find_set(ref: str, folders: List[Path]) -> Path:
    direct = Path(ref).expanduser()
    if ref.strip() and direct.is_dir():
        return direct
    for folder in folders:
        if (folder / ref).is_dir():
            return folder / ref
    raise SetUnreadable(f"no backup set {ref!r} (looked in {', '.join(map(str, folders))})")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", help="the Carnivore state directory (default CARNIVORE_STATE_DIR or ~/Library/Application Support/Carnivore)")
    parser.add_argument("--dest", help="folder holding sets (default /Volumes/ExampleDrive when mounted, else <state dir>/phase-backups)")
    sub = parser.add_subparsers(dest="action", required=True)
    take_p = sub.add_parser("take", help="write a pinned set before a phase")
    take_p.add_argument("phase")
    take_p.add_argument("--config-file", action="append", default=None, help="extra file to cover (default the app's server config.json)")
    verify_p = sub.add_parser("verify", help="check a set, then live data against it")
    verify_p.add_argument("set")
    verify_p.add_argument("--set-only", action="store_true", help="skip the live comparison")
    verify_p.add_argument("--allow-changed", action="append", default=[], metavar="PATTERN", help="a table or file the phase may change, e.g. 'huddle.db:items'")
    sub.add_parser("list", help="list the sets")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Run the CLI. Inputs: argv (list[str] | None). Output: int exit code (0 ok, 1 differences, 2 could not determine)."""
    args = _parser().parse_args(argv)
    try:
        state_dir = targets.resolve_state_dir(args.state_dir)
        folders = candidate_destinations(args.dest, state_dir)
        if args.action == "list":
            for s in list_sets(folders):
                print(f"{s['name']}  " + (f"{s['created_utc']}  dbs={','.join(s['databases'])}  rows={s['rows']}" if s["readable"] else "UNREADABLE MANIFEST"))
            return 0
        if args.action == "take":
            dest = folders[0] if args.dest else targets.default_destination(state_dir)
            dest.mkdir(parents=True, exist_ok=True)
            configs = [Path(c).expanduser() for c in args.config_file] if args.config_file else [targets.DEFAULT_CONFIG_FILE]
            print(take(args.phase, state_dir, dest, configs))
            return 0
        report = verify_set(_find_set(args.set, folders), None if args.set_only else state_dir, args.allow_changed, _by_name)
    except (PhaseBackupError, OSError) as exc:
        print(f"phase_backup: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for line in report.failures:
        print(f"FAIL {line}")
    for line in report.allowed:
        print(f"allowed {line}")
    for line in report.notes:
        print(f"note {line}")
    print("verify: OK" if report.ok else f"verify: {len(report.failures)} difference(s)")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
