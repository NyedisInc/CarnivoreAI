
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Callable, List, Sequence

from src.core.pack.jobs import gitio
from src.core.pack.jobs.types import JobError
from src.core.pack.transport import blobs, bundles


def make_bundle(git_dir: str, ref: str, not_commits: Sequence[str], out_path: str) -> int:
    known = [s for s in not_commits if gitio.run(["cat-file", "-e", f"{s}^{{commit}}"], git_dir=git_dir, check=False).returncode == 0]
    cp = gitio.run(["bundle", "create", out_path, ref, *[f"^{s}" for s in known]], git_dir=git_dir, check=False)
    if cp.returncode != 0:
        if os.path.exists(out_path):
            os.unlink(out_path)
        if b"empty bundle" in cp.stderr.lower():
            raise JobError("nothing_to_send", "the other computer already holds this commit")
        raise JobError("bundle_failed", "git could not make the bundle")
    return os.path.getsize(out_path)


def verify(git_dir: str, bundle_path: str) -> bool:
    return gitio.run(["bundle", "verify", bundle_path], git_dir=git_dir, check=False).returncode == 0


def fetch_bundle(git_dir: str, bundle_path: str, src_ref: str, dst_ref: str, *, fsck: bool = False) -> str:
    if not verify(git_dir, bundle_path):
        raise JobError("bundle_unverified", "the bundle does not verify against this repository")
    gitio.run([*(["-c", "transfer.fsckObjects=true"] if fsck else []), "fetch", "--no-tags", "--force", bundle_path, f"+{src_ref}:{dst_ref}"], git_dir=git_dir, timeout=600.0)
    return gitio.out(gitio.run(["rev-parse", dst_ref], git_dir=git_dir))


def confirmed_tips(open_db: Callable[[], sqlite3.Connection], project_uid: str, peer_install_id: str) -> List[str]:
    conn = open_db()
    try:
        return bundles.read_tips(conn, project_uid, peer_install_id, direction="out")
    finally:
        conn.close()


async def send_bundle(request: blobs.Request, path: str) -> str:
    return await blobs.send_file(request, path, blob_id=blobs.new_id(), kind="bundle")


def received_path(state_dir: Path, blob_id: str, *, sender: str) -> Path:
    return blobs.Inbox(Path(state_dir) / "pack" / "inbox").sealed_path(blob_id, peer=sender)


def consumed(state_dir: Path, blob_id: str) -> None:
    blobs.Inbox(Path(state_dir) / "pack" / "inbox").remove(blob_id)
