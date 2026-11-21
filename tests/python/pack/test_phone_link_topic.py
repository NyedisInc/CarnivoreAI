
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional, Tuple

import pytest

from src.core import resource_push
from src.core.phone_link.pairing import PairingStore
from src.core.phone_link.tunnel_client import TunnelClient
from src.core.pack.relay import owner_side
from src.core.pack.relay.ddl import apply_pack_relay
from src.core.resource_push import topics


@pytest.fixture
def announced(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    seen: List[str] = []
    monkeypatch.setattr(resource_push, "notify", lambda topic, *a, **k: seen.append(topic))
    return seen


def test_phone_link_is_a_listed_topic() -> None:
    assert topics.PHONE_LINK in topics.RESOURCE_TOPICS


def test_pairing_store_tells_its_hooks_on_every_panel_write(tmp_path: Path) -> None:
    store = PairingStore(path=tmp_path / "pl.db")
    fired: List[int] = []
    store.on_change.append(lambda: fired.append(1))
    store.set_enabled(True)
    assert fired
    fired.clear()
    store.open_window()
    assert fired
    fired.clear()
    store.close_window()
    assert fired
    store.close()


def test_a_device_pairing_and_its_revoke_are_announced(tmp_path: Path) -> None:
    store = PairingStore(path=tmp_path / "pl.db")
    window = store.open_window()
    claim = store.claim_code(window.code, "203.0.113.5", "phone")
    assert claim is not None
    fired: List[int] = []
    store.on_change.append(lambda: fired.append(1))
    assert store.complete_pending(claim.handle) is not None
    assert fired
    fired.clear()
    device = store.devices()[0]
    assert store.revoke(device.id) is True
    assert fired
    store.close()


def test_tunnel_status_changes_fire_the_hook_once_each() -> None:
    told: List[int] = []
    tunnel = TunnelClient(url="wss://x", session=SimpleNamespace(), local_port=lambda: None, streams=SimpleNamespace(),
                          on_status=lambda: told.append(1))
    tunnel.status = "connecting"
    tunnel.status = "connecting"
    tunnel.status = "connected"
    assert len(told) == 2
    assert tunnel.connected is True


def test_push_store_saves_announce_the_topic(tmp_path: Path, announced: List[str]) -> None:
    from src.core.web_push.store import SubscriptionStore

    store = SubscriptionStore(tmp_path)
    row = store.add("https://push.example/e1", "k", "a", device_id="d1")
    assert topics.PHONE_LINK in announced
    announced.clear()
    store.record_result(row["id"], 201)
    assert announced == [topics.PHONE_LINK]


def test_arming_announces_even_when_nothing_is_pushed(tmp_path: Path) -> None:
    db = tmp_path / "relay.db"

    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db))
        conn.isolation_level = None
        return conn

    with open_db() as conn:
        apply_pack_relay(conn)
    told: List[int] = []

    async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        return 200, {"ok": True}

    relay = owner_side.Relay(open_db=open_db, peer=lambda iid: (post, [owner_side.CAP_CREDENTIALS]), notify=lambda: told.append(1),
                             self_id="iid-owner", candidates=lambda: ["peer-b"])
    no_token = SimpleNamespace(access_token=None, expires_at=None)
    assert asyncio.run(relay.push_account("fresh", no_token)) == []
    assert told, "arming wrote rows but never announced pack_relay"


def test_manager_announces_hostname_error_tunnel_and_pairing(tmp_path: Path, announced: List[str], monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config.relay import RelayConfig
    from src.core.phone_link import manager as manager_mod

    built: List[Any] = []

    class FakeTunnel:

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.status = "stopped"
            built.append(self)

        def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class FakeSession:

        async def ensure_registered(self) -> str:
            return "devid"

    class Mgr(manager_mod.PhoneLinkManager):
        async def _session_for(self) -> Any:
            return FakeSession()

    monkeypatch.setattr(manager_mod, "TunnelClient", FakeTunnel)
    m = Mgr(app=None, config=RelayConfig(), state_dir=tmp_path, db_path=tmp_path / "c.db", version="1.0.0")
    try:
        m.hostname = "h.link.example"
        m.error = "boom"
        assert announced.count(topics.PHONE_LINK) == 2
        m.error = "boom"
        assert announced.count(topics.PHONE_LINK) == 2
        announced.clear()
        m.pairing.set_enabled(True)
        assert topics.PHONE_LINK in announced
        announced.clear()
        asyncio.run(m._start())
        assert built and built[0].kwargs["on_status"] == m.announce
        assert topics.PHONE_LINK in announced
    finally:
        m.pairing.close()


def test_pairing_hooks_never_run_under_the_store_lock(tmp_path: Path) -> None:
    from src.core.phone_link.pairing import MAX_PENDING_ATTEMPTS

    store = PairingStore(path=tmp_path / "pl.db")
    held: List[bool] = []
    store.on_change.append(lambda: held.append(store._lock._is_owned()))  # type: ignore[attr-defined]
    store.set_enabled(True)
    window = store.open_window()
    claim = store.claim_code(window.code, "203.0.113.5", "phone")
    assert claim is not None
    for _ in range(MAX_PENDING_ATTEMPTS + 1):
        store.begin_attempt(claim.handle)
    window = store.open_window()
    claim = store.claim_secret(window.secret, "203.0.113.5", "phone")
    assert claim is not None
    store.close_window()
    window = store.open_window()
    claim = store.claim_code(window.code, "203.0.113.5", "phone")
    store.begin_attempt(claim.handle)
    for _ in range(MAX_PENDING_ATTEMPTS):
        store.begin_attempt(claim.handle)
    store.drop_if_spent(claim.handle)
    assert held and not any(held)
    store.close()
