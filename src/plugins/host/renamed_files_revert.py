"""The reverse switch of a renamed plugin's attachments move (#3260 slice S3; Joe (ccsliinc), 2026-11-22, answer 11; review r1 M6, m9).

``python3 -m src.plugins.host.renamed_files_revert [--state-dir DIR] [--pair OLD=NEW] [--port N]`` removes the copy the boot step
(``renamed_files.py``) published in ``cplugs/<new>/files``, so a re-upgrade copies again whatever changed in the old folder meanwhile.
It never loses a file:

- It REFUSES while the app is running (its port answers on 127.0.0.1): an upload could land mid-revert. It never stops anything.
- It removes the copy only while the copy holds NOTHING the marker does not: every file there must be listed with the same sha256. A copy
  that lost files since the move (the owner removed some) holds a subset and loses nothing, so it is reverted and the count reported.
- It looks TWICE: the copy is first renamed aside (``cplugs/<new>/.files.reverting``), then hashed again right before it is deleted; any
  difference renames it back and refuses. A ``.files.reverting`` folder left by an earlier crash may hold the only copy of something, so
  its presence refuses too, and it is never deleted here.
- Order: the copy goes aside, then the marker goes, then the aside copy. A crash in between leaves a marker over no copy, which the next
  boot sets aside and copies again (``renamed_files._trusted_marker``), never a deleted file.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.plugins.host import renamed_files
from src.plugins.host.app_probe import app_answers
from src.plugins.host.renamed_files import FilesOutcome, files_dir, fsync_dir
from src.plugins.sdk.renamed_files import marker_name, moved_list

logger = structlog.get_logger()

REVERTING_NAME = ".files.reverting"
PROBE_TIMEOUT_S = 0.5
AppRunning = Callable[[], bool]


class RevertRefused(OSError):
    pass


def _beyond(listed: Mapping[str, str], have: Mapping[str, str]) -> Dict[str, int]:
    return {"added": len(set(have) - set(listed)), "changed": sum(1 for rel in set(have) & set(listed) if have[rel] != listed[rel])}


def _hashes(root: Path) -> Dict[str, str]:
    return {rel: sha for rel, (sha, _size) in renamed_files.listing(root).items()}


def _set_aside(dest: Path, aside: Path, listed: Mapping[str, str], names: Sequence[str]) -> int:
    os.replace(dest, aside)
    fsync_dir(dest.parent)
    second = _beyond(listed, _hashes(aside))
    if any(second.values()):
        try:
            os.replace(aside, dest)
        except OSError as exc:
            logger.error("cplug_renamed_files_revert_put_back_failed", old=names[0], new=names[1], aside=str(aside), error=str(exc)[:200])
        raise RevertRefused(f"the copy changed while it was being removed: {second}")
    return len(set(listed) - set(_hashes(aside)))


def _revert_one(state_dir: Path, old: str, new: str) -> Tuple[str, int]:
    src, dest = files_dir(state_dir, old), files_dir(state_dir, new)
    marker = src / marker_name(new)
    if not marker.exists():
        return "none", 0
    listed = moved_list(marker)
    if listed is None:
        raise RevertRefused(f"{marker} cannot be read, so the copy cannot be proven unchanged")
    aside = dest.parent / REVERTING_NAME
    if os.path.lexists(aside):
        raise RevertRefused(f"{aside} is left from an earlier run and may hold the only copy of a file; look at it first")
    have = _hashes(dest)
    first = _beyond(listed, have)
    if any(first.values()):
        logger.warning("cplug_renamed_files_revert_kept", old=old, new=new, reason="files were added or changed since the move", **first)
        return "kept", 0
    removed = len(set(listed) - set(have))
    if dest.is_dir():
        try:
            removed = _set_aside(dest, aside, listed, (old, new))
        except RevertRefused as exc:
            logger.warning("cplug_renamed_files_revert_kept", old=old, new=new, reason=str(exc)[:200])
            return "kept", 0
    marker.unlink()
    fsync_dir(src)
    if os.path.lexists(aside):
        shutil.rmtree(aside)
    logger.info("cplug_renamed_files_reverted", old=old, new=new, files=len(listed) - removed, removed_since_move=removed)
    return "reverted", removed


def revert(state_dir: Path, renames: Optional[Mapping[str, str]] = None, *, app_running: AppRunning) -> FilesOutcome:
    outcome = FilesOutcome()
    pairs = dict(renamed_files.configured_renames() if renames is None else renames)
    running = app_running()
    for old, new in pairs.items():
        if running:
            outcome.state[old], outcome.failed = "app_running", True
            logger.warning("cplug_renamed_files_revert_refused", old=old, new=new, reason="the app is running; stop it first")
            continue
        try:
            state, removed = _revert_one(Path(state_dir), old, new)
        except OSError as exc:
            outcome.state[old], outcome.failed = "failed", True
            logger.error("cplug_renamed_files_revert_failed", old=old, new=new, error_type=type(exc).__name__, error=str(exc)[:300])
            continue
        if state == "reverted":
            outcome.removed[old] = removed
        outcome.state[old] = state
        outcome.failed = outcome.failed or state == "kept"
    return outcome


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="renamed_files_revert", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--state-dir", type=Path, default=None, help="the app state directory (default: the live one)")
    parser.add_argument("--pair", action="append", default=[], metavar="OLD=NEW", help="a rename; default: every renamed_from in the manifests")
    parser.add_argument("--port", type=int, default=None, help="the app's port to probe (default: the configured one)")
    args = parser.parse_args(argv)
    pairs: Optional[Dict[str, str]] = dict(p.split("=", 1) for p in args.pair if "=" in p) if args.pair else None
    if args.pair and (pairs is None or len(pairs) != len(args.pair)):
        parser.error("--pair takes OLD=NEW")
    from src.config import settings

    state_dir = args.state_dir if args.state_dir is not None else settings.get_state_dir()
    port = args.port if args.port is not None else settings.port
    outcome = revert(state_dir, pairs, app_running=lambda: app_answers(port))
    lines: List[str] = [f"{old}: {state}" + (f" ({outcome.removed[old]} removed since the move)" if outcome.removed.get(old) else "")
                        for old, state in sorted(outcome.state.items())]
    print("\n".join(lines) or "nothing to revert")
    return 1 if outcome.failed else 0


if __name__ == "__main__":
    sys.exit(main())
