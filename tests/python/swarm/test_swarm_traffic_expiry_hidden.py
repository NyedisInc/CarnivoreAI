
from __future__ import annotations

import asyncio

from src.core.crosstalk import store as crosstalk_store
from src.core.swarm import body, stream_sources


def _row(mid, sender_key, text, source="crosstalk"):
    return {"id": mid, "source": source, "sender_key": sender_key, "receiver_key": "u-me", "sender_name": "x",
            "receiver_name": "me", "receiver_id": "ses_me", "text": text, "thread": "t", "in_reply_to": None,
            "status": "delivered", "reason": None, "delivered_at": 1.0, "created_at": 1.0}


def test_the_chat_drops_expiry_notices_and_keeps_the_rest(monkeypatch):
    rows = [_row("m-1", "u-peer", "hello"),
            _row("m-2", "crosstalk-system", "message m-9 to ses_gone expired after 24 hours", source="system"),
            _row("m-3", "crosstalk-system", "ses_peer went idle", source="system")]

    async def run_db(fn):
        return ("u-me",)

    monkeypatch.setattr(body, "run_db", run_db)
    monkeypatch.setattr(crosstalk_store, "recent_for", lambda key, limit: rows)
    entries = asyncio.run(stream_sources.crosstalk_traffic({"session_row_id": 7}, 50))
    assert [e["id"] for e in entries] == ["xt:m-1", "xt:m-3"]
