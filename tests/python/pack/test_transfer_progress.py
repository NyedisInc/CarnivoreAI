
from __future__ import annotations

import asyncio
from contextlib import closing

from src.core import resource_push
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.pack import progress
from src.core.pack.move import op_status, ops
from src.core.pack.transport import blobs


def test_bytes_steps_acks_and_errors_are_recorded_and_pushed(tmp_path, monkeypatch) -> None:
    pushed = []
    monkeypatch.setattr(resource_push, "notify", lambda topic: pushed.append(topic))
    monkeypatch.setattr(resource_push, "notify_coalesced", lambda topic, key, interval: pushed.append(topic))
    assert ensure_db_migrated(tmp_path).status == "ok"
    blob = tmp_path / "x.bin"
    blob.write_bytes(b"a" * 3000)

    async def request(method, path, *, content=None, headers=None, json=None):
        return (200, {"received": 0}) if method == "GET" else (200, {})

    async def run() -> None:
        progress.bind("op-1")
        await blobs.send_file(request, str(blob), blob_id="blob-0123456789", kind="transcripts", chunk_bytes=1000)

    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        ops.create(conn, op_id="op-1", role="source", session_uuid="s", claude_session_uuid=None, source_install_id="a", target_install_id="b",
                   detail={"name": "x", "mode": "move"})
        ops.update(conn, "op-1", "source", step="carry")
        asyncio.run(run())
        ops.update(conn, "op-1", "source", state="failed", error_code="carry_failed", detail={"error": "it broke at /nowhere"})
        got = op_status.one(conn, "op-1")["progress"]
    assert (got["step"], got["bytes_done"], got["bytes_total"]) == ("carry", 3000, 3000)
    text = [line["text"] for line in got["log"]]
    assert "step carry started" in text and any("the other computer verified" in t for t in text) and any(t.startswith("error carry_failed") for t in text)
    assert "pack_ops" in pushed and "pack_ops:op-1" in pushed
