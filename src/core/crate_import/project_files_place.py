
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.safe_io.atomic_write import atomic_write_bytes
from src.core.blobcodec.place import PlaceConflict, PlaceMismatch, write_verified
from src.core.crate_format.constants import M_PROJECT_PATCH
from src.core.crate_format.errors import CrateError
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import files_apply, files_place, undo
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.hooks import ApplyHooks
from src.core.crate_import.model import ImportFailed
from src.core.crate_import.project_files_in import LINK_CHANGED, LINK_ESCAPES, LINK_EXISTS, LinkPlan, SidePlan
from src.core.project_move.paths import is_within

logger = structlog.get_logger()

GIT_FILE = "project_git.json"
PATCH_FILE = "uncommitted.patch"


def _link_text(reader: CrateReader, link: LinkPlan) -> Optional[str]:
    try:
        raw = b"".join(reader.file_chunks(link.record))
    except CrateError:
        return None
    if hashlib.sha256(raw).hexdigest() != link.record.content_sha256:
        return None
    text = raw.decode("utf-8", "replace")
    return text if text == link.target else None


def _place_link(reader: CrateReader, link: LinkPlan, side: Path, hooks: ApplyHooks, placed: files_apply.PlacedFiles) -> str:
    text = _link_text(reader, link)
    if text is None:
        return LINK_CHANGED
    dest = side / link.rel
    if files_place.contained(dest, side) is not None:
        return LINK_ESCAPES
    if os.path.lexists(dest):
        return LINK_EXISTS
    files_apply.make_parents(dest, side, hooks, placed, side)
    files_apply.record_undo(hooks, placed, undo.link_entry(dest, text, side))
    try:
        os.symlink(text, dest)
    except FileExistsError:
        return LINK_EXISTS
    if not is_within(os.path.realpath(dest), os.path.realpath(side)):
        os.unlink(dest)
        return LINK_ESCAPES
    return ""


def ensure_root(root: Path, hooks: ApplyHooks, placed: files_apply.PlacedFiles) -> None:
    missing: list = []
    folder = Path(root)
    while not os.path.lexists(folder) and folder != folder.parent:
        missing.append(folder)
        folder = folder.parent
    if missing and not os.path.isdir(folder):
        raise ImportFailed(files_apply.E_IO, f"{folder}: not a folder", rolled_back=False)
    outer = missing[-1] if missing else None
    for made in reversed(missing):
        hooks.check()
        files_apply.record_undo(hooks, placed, {**undo.dir_entry(made, outer), "project_root": True})
        try:
            os.mkdir(made, 0o755)
        except FileExistsError:
            continue
        except OSError as exc:
            raise ImportFailed(files_apply.E_IO, f"{made}: {type(exc).__name__}", rolled_back=False) from exc


def place_side(reader: CrateReader, plan: SidePlan, hooks: ApplyHooks, placed: files_apply.PlacedFiles) -> None:
    side = plan.path
    if plan.already_here:
        return
    if plan.into_root:
        placed.root_side = side
        if not side.is_dir() or side.is_symlink():
            raise ImportFailed(files_apply.E_FILE_CHANGED, f"{side}: the project folder is gone", rolled_back=False)
    else:
        files_apply.record_undo(hooks, placed, undo.dir_entry(side, side))
        try:
            os.mkdir(side, 0o755)
        except FileExistsError as exc:
            raise ImportFailed(files_apply.E_FILE_CHANGED, f"{side}: the folder appeared after the preview", rolled_back=False) from exc
        except OSError as exc:
            raise ImportFailed(files_apply.E_IO, f"{side}: {type(exc).__name__}", rolled_back=False) from exc
    for record, dest in plan.files:
        hooks.check()
        problem = files_place.contained(dest, side)
        if problem is not None:
            raise ImportFailed(files_apply.E_UNSAFE, f"{dest}: {problem}", rolled_back=False)
        try:
            files_apply.make_parents(dest, side, hooks, placed, side)
            files_apply.record_undo(hooks, placed, undo.file_entry(dest, record.content_sha256, record.length, side))
            written = write_verified(reader.file_chunks(record), dest, length=record.length, sha256=record.content_sha256,
                                     mode=record.mode & 0o777, mtime_ns=record.mtime_ns)
        except PlaceConflict as exc:
            raise ImportFailed(files_apply.E_FILE_CHANGED, f"{exc}: a file appeared in the new folder", rolled_back=False) from exc
        except (PlaceMismatch, CrateError) as exc:
            raise ImportFailed(files_apply.E_CRATE_BYTES, f"{record.rel}: {type(exc).__name__}", rolled_back=False) from exc
        except OSError as exc:
            raise ImportFailed(files_apply.E_IO, f"{dest}: {type(exc).__name__}", rolled_back=False) from exc
        placed.project_written += 1
        placed.bytes += written
        hooks.add(written, 1)
    for link in (lk for lk in plan.links if not lk.why):
        try:
            why = _place_link(reader, link, side, hooks, placed)
        except OSError as exc:
            raise ImportFailed(files_apply.E_IO, f"{link.rel}: {type(exc).__name__}", rolled_back=False) from exc
        if why:
            placed.project_links_skipped.append(f"{link.rel}: {why}")
        else:
            placed.project_links += 1


def _write_atomic(path: Path, data: bytes) -> None:
    try:
        if path.is_file() and path.read_bytes() == data:
            return
    except OSError as exc:
        logger.warning("crate_import_receipt_unreadable", path=str(path), error=type(exc).__name__)
    atomic_write_bytes(path, data)


def keep_git_state(reader: CrateReader, plan: SidePlan, env: ImportEnv, import_id: str) -> Dict[str, Any]:
    folder = env.backup_dir(import_id).parent
    out: Dict[str, Any] = {"patch": None, "git": None}
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if plan.git is not None:
        _write_atomic(folder / GIT_FILE, json.dumps(plan.git, sort_keys=True, indent=1).encode())
        out["git"] = str(folder / GIT_FILE)
    if plan.patch:
        _write_atomic(folder / PATCH_FILE, b"".join(reader.iter_member(M_PROJECT_PATCH)))
        out["patch"] = str(folder / PATCH_FILE)
    return out


def receipt_block(plan: Optional[SidePlan], kept: Optional[Dict[str, Any]], placed: files_apply.PlacedFiles) -> Dict[str, Any]:
    if plan is None:
        return {}
    skipped = [f"{lk.rel}: {lk.why}" for lk in plan.links if lk.why] + list(placed.project_links_skipped)
    return {**plan.view(), "links_not_created": skipped, "kept": kept or {}}
