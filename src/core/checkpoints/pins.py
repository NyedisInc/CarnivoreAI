
from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

import structlog

from src.core.checkpoints.capture import repo_lock
from src.core.checkpoints.store import KIND_TURN, CheckpointStore
from src.core.swarm.gitrun import run_git

logger = structlog.get_logger()

MARKER = "carnivore checkpoint pins\n"
PACK_TIMEOUT_S = 600.0


def pinned_commits(store: CheckpointStore, shadow: str) -> List[str]:
    found = set()
    for session in store.sessions():
        pins = store.pinned_prompts(session)
        found |= {cp.commit_sha for cp in store.for_session(session)
                  if cp.shadow == shadow and cp.kind == KIND_TURN and cp.prompt_uuid in pins}
    return sorted(found)


def _marked_packs(pack_dir: Path) -> List[Path]:
    out = []
    for keep in sorted(pack_dir.glob("pack-*.keep")) if pack_dir.is_dir() else []:
        try:
            if keep.read_text() == MARKER:
                out.append(keep)
        except OSError:
            continue
    return out


def rebuild(store: CheckpointStore, shadow: str) -> Optional[str]:
    root = Path(shadow)
    pack_dir = root / "objects" / "pack"
    with repo_lock(root):
        commits = pinned_commits(store, shadow)
        new: Optional[str] = None
        if commits:
            listed = run_git(root, "rev-list", "--objects", *commits, timeout=PACK_TIMEOUT_S, low_priority=True)
            if listed.returncode != 0:
                raise OSError("rev-list of the pinned snapshots failed")
            packed = run_git(root, "-c", "pack.writeBitmaps=false", "pack-objects", "-q", str(pack_dir / "pack"),
                             timeout=PACK_TIMEOUT_S, low_priority=True,
                             input_bytes=listed.stdout.encode("utf-8", "surrogateescape"))
            new = packed.stdout.strip()
            if packed.returncode != 0 or not new or not (pack_dir / f"pack-{new}.pack").is_file():
                raise OSError("pack-objects of the pinned snapshots failed")
            (pack_dir / f"pack-{new}.keep").write_text(MARKER)
        released = False
        for keep in _marked_packs(pack_dir):
            if keep.name != f"pack-{new}.keep":
                keep.unlink()
                released = True
        if released:
            done = run_git(root, "-c", "repack.writeBitmaps=false", "repack", "-a", "-d", "-l", "-q",
                           timeout=PACK_TIMEOUT_S, low_priority=True)
            if done.returncode != 0:
                logger.warning("checkpoint_pin_repack_failed", shadow=shadow, rc=done.returncode)
    return new


def refresh_session(store: CheckpointStore, session_uuid: str) -> None:
    for shadow in sorted({cp.shadow for cp in store.for_session(session_uuid)}):
        try:
            rebuild(store, shadow)
        except OSError as exc:
            logger.warning("checkpoint_pin_copy_failed", shadow=shadow, error=str(exc))


def refresh_session_soon(store: CheckpointStore, session_uuid: str) -> None:
    if not store.for_session(session_uuid):
        return
    threading.Thread(target=refresh_session, args=(store, session_uuid), name="checkpoint-pins", daemon=True).start()
