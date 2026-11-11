
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from src.core.pack.relay import approval, owner_side, targets
from src.core.pack.relay.ddl import apply_pack_relay


def _db(tmp_path: Path):
    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(tmp_path / "relay.db"))
        conn.isolation_level = None
        return conn
    with open_db() as conn:
        apply_pack_relay(conn)
    return open_db


def _relay(open_db, sent):
    async def post(method, path, body):
        sent.append(body["account_key"])
        return 200, {"ok": True}
    return owner_side.Relay(open_db=open_db, peer=lambda iid: (post, [owner_side.CAP_CREDENTIALS]), notify=lambda: None, self_id="iid-main",
                            candidates=lambda: ["peer-new", "peer-old"], approved=approval.reader(open_db))


def test_no_push_before_yes_push_after_yes_grandfathered_unaffected_and_no_mcp_route(tmp_path):
    open_db = _db(tmp_path)
    with open_db() as conn:
        targets.set_machines(conn, "work", ["peer-old"], "iid-main")
    sent: list = []
    relay = _relay(open_db, sent)
    cred = SimpleNamespace(access_token="fake-access", expires_at=datetime.now(timezone.utc) + timedelta(hours=8), scopes=(),
                           subscription_type=None, rate_limit_tier=None)

    assert asyncio.run(relay.push_account("work", cred)) == ["peer-old"]
    with open_db() as conn:
        assert approval.answers(conn) == {"peer-old": "yes"}
        assert approval.pending(approval.answers(conn), ["peer-new", "peer-old"]) == ["peer-new"]
        targets.arm_default(conn, "work", ["peer-new"], "iid-main")
    later = SimpleNamespace(**{**cred.__dict__, "expires_at": cred.expires_at + timedelta(hours=1)})
    assert asyncio.run(relay.push_account("work", later)) == ["peer-old"]
    with open_db() as conn:
        approval.record(conn, "peer-new", "no")
    even_later = SimpleNamespace(**{**cred.__dict__, "expires_at": cred.expires_at + timedelta(hours=2)})
    assert asyncio.run(relay.push_account("work", even_later)) == ["peer-old"]
    with open_db() as conn:
        approval.record(conn, "peer-new", "yes")
    assert asyncio.run(relay.push_account("work", even_later)) == ["peer-new"]

    mcp_src = "".join(p.read_text() for p in Path("src/core/mcp").rglob("*.py"))
    assert "relay-approval" not in mcp_src and "relay_approval" not in mcp_src
