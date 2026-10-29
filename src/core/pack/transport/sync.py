
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from contextlib import closing
from typing import Any, Callable, Dict

from src.core.db import transaction
from src.core.pack.transport import blobs, bundles

APPLY_PATH = "/federation/pack/bundle/apply"


async def carry_bundle(*, repo: str, project_uid: str, peer_install_id: str, request: blobs.Request,
                       open_db: Callable[[], sqlite3.Connection], outbox: str, air_gap: bool, full: bool = False) -> Dict[str, Any]:
    def read_tips():
        with closing(open_db()) as conn:
            return bundles.read_tips(conn, project_uid, peer_install_id)

    branch = await asyncio.to_thread(bundles.carry_branch, repo)
    os.makedirs(outbox, mode=0o700, exist_ok=True)
    known = await asyncio.to_thread(read_tips)
    fd, path = tempfile.mkstemp(prefix="out-", suffix=".bundle", dir=outbox)
    os.close(fd)
    os.unlink(path)
    try:
        tips = await asyncio.to_thread(lambda: bundles.make_bundle(repo, path, known_tips=known, air_gap=air_gap, full=full))
        if tips is None:
            return {"sent": False, "reason": "nothing_new"}
        blob_id = blobs.new_id()
        await blobs.send_file(request, path, blob_id=blob_id, kind="bundle")
        remote = None if air_gap else await asyncio.to_thread(bundles.origin_url, repo)
        status, answer = await request("POST", APPLY_PATH, json={"blob_id": blob_id, "project_uid": project_uid,
                                                                  "branch": branch, "remote": remote})
        if status != 200:
            detail = answer.get("detail") if isinstance(answer, dict) else None
            raise blobs.BlobError(detail.get("code", "apply_failed") if isinstance(detail, dict) else "apply_failed", status)

        def record() -> None:
            with closing(open_db()) as conn:
                with transaction(conn):
                    bundles.record_tips(conn, project_uid, peer_install_id, tips)

        await asyncio.to_thread(record)
        return {"sent": True, "refs": int((answer or {}).get("refs", 0))}
    finally:
        if os.path.exists(path):
            os.unlink(path)
