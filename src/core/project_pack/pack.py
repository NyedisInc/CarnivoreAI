
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import structlog

from src.core.project_pack import archive_io, inventory, manifest, store, verify
from src.core.project_pack import constants as K
from src.core.project_pack.env import PackEnv
from src.core.project_pack.jobs import Progress
from src.core.project_pack.plan import PackPlan
from src.core.project_pack.trash import TrashError
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

class PackError(Exception):
    pass


EXPECTED = (PackError, inventory.InventoryError, verify.VerifyError, archive_io.ArchiveToolError, TrashError,
            manifest.ManifestError, OSError, sqlite3.Error)


def archive_name_for(root: str, today: Optional[dt.date] = None) -> str:
    day = (today or dt.date.today()).isoformat()
    return f"{os.path.basename(root)}{K.ARCHIVE_INFIX}{day}{K.ARCHIVE_SUFFIX}"


def stamp_now() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def unlink_created(root: str, names: List[str]) -> None:
    for name in names:
        try:
            os.unlink(os.path.join(root, name))
        except FileNotFoundError:
            pass


def move_entries(src_dir: str, dst_dir: str, names: List[str]) -> List[Tuple[str, str]]:
    moved: List[Tuple[str, str]] = []
    try:
        for name in names:
            pair = (os.path.join(src_dir, name), os.path.join(dst_dir, name))
            os.rename(*pair)
            moved.append(pair)
    except OSError:
        reverse_moves(moved)
        raise
    return moved


def reverse_moves(moved: List[Tuple[str, str]]) -> List[str]:
    errors: List[str] = []
    for src, dst in reversed(moved):
        try:
            os.rename(dst, src)
        except OSError as exc:
            errors.append(f"{dst} -> {src}: {exc}")
            logger.error("project_pack_reverse_failed", src=src, dst=dst, error=str(exc))
    return errors


@dataclass
class JobState:

    name: str
    staging: str
    names: List[str] = field(default_factory=list)
    sha256: str = ""
    files: int = 0
    bytes: int = 0
    trashed: bool = False

    @property
    def partial(self) -> str:
        return self.name + K.PARTIAL_SUFFIX

    @property
    def created(self) -> List[str]:
        return [self.partial, self.name, K.MANIFEST_NAME, K.README_NAME]


def run_pack(open_conn: Callable[[], sqlite3.Connection], plan: PackPlan, env: PackEnv, progress: Progress,
             job_id: str) -> None:
    conn = open_conn()
    pid, root = plan.project["id"], plan.root
    job = JobState(archive_name_for(root), os.path.join(root, K.ORIGINALS_PREFIX + stamp_now()))
    try:
        store.put(conn, pid, state=K.STATE_PACKING, job_id=job_id, job_started_at=utc_now(), last_error=None,
                  accepted_local_only="; ".join(plan.local_only) or None)
        _write_and_prove(conn, plan, env, progress, job)
        _retire(conn, plan, env, progress, job)
        logger.info("project_packed", project_id=pid, archive=job.name, logical_bytes=job.bytes)
    except EXPECTED as exc:
        _undo(conn, pid, root, job, f"{type(exc).__name__}: {exc}")
    except BaseException as exc:  # noqa: BLE001
        _undo(conn, pid, root, job, f"unexpected {type(exc).__name__}: {exc}")
        raise
    finally:
        conn.close()


def _write_and_prove(conn: sqlite3.Connection, plan: PackPlan, env: PackEnv, progress: Progress,
                     job: JobState) -> None:
    root, partial, name = plan.root, os.path.join(plan.root, job.partial), os.path.join(plan.root, job.name)
    own = set(job.created)
    tree = inventory.walk(root, own)
    before = inventory.stat_signature(tree.entries)
    progress.set_phase("hashing", tree.logical_bytes)
    inventory.hash_files(root, tree.entries, progress.add)
    progress.set_phase("compressing")
    archive_io.create_archive(root, tree.top_level(), partial, env.level)
    store.put(conn, plan.project["id"], state=K.STATE_VERIFYING)
    progress.set_phase("verifying", tree.logical_bytes)
    verify.verify_archive(partial, tree.entries, progress.add)
    if inventory.stat_signature(inventory.walk(root, own).entries) != before:
        raise PackError("the folder changed while it was being packed (an edit, or iCloud delivered a change); "
                        "nothing was removed, plan again")
    job.sha256 = inventory.sha256_file(partial)
    fd = os.open(partial, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(partial, name)
    manifest.write_sidecar(root, job.name, job.sha256, os.stat(name).st_size, tree.entries, env.level)
    manifest.write_readme(root, job.name)
    job.names, job.files, job.bytes = tree.top_level(), tree.file_count, tree.logical_bytes


def _retire(conn: sqlite3.Connection, plan: PackPlan, env: PackEnv, progress: Progress, job: JobState) -> None:
    root, pid = plan.root, plan.project["id"]
    st = os.stat(os.path.join(root, job.name))
    store.put(conn, pid, state=K.STATE_RETIRING, archive_name=job.name, archive_sha256=job.sha256,
              archive_bytes=st.st_size, archive_mtime_ns=st.st_mtime_ns, logical_bytes=job.bytes, file_count=job.files)
    progress.set_phase("moving originals to trash")
    os.mkdir(job.staging)
    moved = move_entries(root, job.staging, job.names)
    try:
        env.trash([job.staging])
    except TrashError:
        reverse_moves(moved)
        raise
    job.trashed = True
    store.put(conn, pid, state=K.STATE_PACKED, packed_at=utc_now(), last_error=None)
    for child in plan.children:
        store.put(conn, child["id"], notify=False, state=K.STATE_PACKED, packed_in=pid, archive_name=job.name,
                  packed_at=utc_now(), last_error=None)


def _undo(conn: sqlite3.Connection, pid: int, root: str, job: JobState, reason: str) -> None:
    if job.trashed:
        logger.error("project_pack_record_failed_after_trash", project_id=pid, reason=reason)
        return
    errors: List[str] = []
    try:
        os.rmdir(job.staging)
    except FileNotFoundError:
        pass
    except OSError as exc:
        errors.append(f"{job.staging}: {exc}")
    if not errors:
        unlink_created(root, job.created)
    note = reason + (f" (could not undo: {'; '.join(errors)}; the archive was kept)" if errors else "")
    store.mark_unpacked(conn, pid, last_error=note)
    logger.error("project_pack_failed", project_id=pid, reason=note)
