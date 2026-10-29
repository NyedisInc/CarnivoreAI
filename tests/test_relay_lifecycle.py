
from __future__ import annotations

import asyncio
import functools
import json
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_relaylc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_relaylc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config.relay import RelayConfig
from src.core import relay_keychain, relay_lifecycle, relay_publisher
from src.core import relay_protocol as proto
from src.core.relay_identity import device_key as dk
from src.core.relay_identity import publish_auth
from src.core.relay_identity.session import DeviceSession
from tests.relay_v2_support import Issuer
from tests.test_relay_identity import FakeControl, FakeKeychain
from tests.test_relay_publisher import SESSION_ID, _FakeConnection, _registry, _Tripwire, _until

pytestmark = pytest.mark.real_relay_start


class _Store:

    def __init__(self, live: bool) -> None:
        self.live = live

    async def live_expiry_by_session(self):
        return {SESSION_ID: 4_000_000_000} if self.live else {}

    async def live_relay_declarations(self):
        return []


@pytest.fixture
def wired(monkeypatch, tmp_path):
    from src.core.db import db_path_for
    from src.core.db_migration import ensure_db_migrated

    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.0.0")
    for name in proto.TOKEN_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(relay_keychain, "read_publish_token", lambda: None)
    ns = SimpleNamespace(keychain=FakeKeychain(), control=FakeControl(Issuer()),
                         dials=[], built=[], hang=False)
    monkeypatch.setattr(relay_publisher, "DeviceSession", functools.partial(
        DeviceSession, call=ns.control, sleep=lambda s: asyncio.sleep(0),
        key_loader=lambda install: dk.load_or_create(
            install, read=ns.keychain.read, write=ns.keychain.write)))

    class _Never:
        async def __aenter__(self):
            await asyncio.Event().wait()

        async def __aexit__(self, *exc):
            return False

    def connector(url, dial):
        ns.dials.append((url, dial))
        return _Never() if ns.hang else _FakeConnection()

    real = relay_publisher.RelayPublisher

    def counted(**kw):
        publisher = real(connector=connector, sleep=lambda s: asyncio.sleep(0), **kw)
        ns.built.append(publisher)
        return publisher

    monkeypatch.setattr(relay_publisher, "RelayPublisher", counted)
    ns.build = lambda store: relay_lifecycle.build(
        RelayConfig(), registry=_registry(), store=store,
        db_path=db_path_for(state), version="v1.8.1")
    return ns


@pytest.mark.asyncio
async def test_boot_with_no_live_link_sends_nothing_off_the_machine(wired):
    lifecycle = wired.build(_Store(live=False))
    await lifecycle.start_if_live()
    await asyncio.sleep(0.2)
    try:
        assert lifecycle.publisher is None
        assert wired.built == [] and wired.dials == [] and wired.control.calls == []
        assert wired.keychain.writes == 0 and wired.keychain.items == {}
    finally:
        await lifecycle.aclose()


@pytest.mark.asyncio
async def test_boot_with_a_live_link_connects_at_once(wired):
    lifecycle = wired.build(_Store(live=True))
    await lifecycle.start_if_live()
    try:
        assert lifecycle.publisher is not None
        assert await lifecycle.publisher.wait_connected(3.0)
        assert [path for path, _, _ in wired.control.calls][:2] == ["/devices", "/token"]
        assert wired.dials[0][0] == "wss://relay.carnivore.ai/publish"
        assert wired.dials[0][1].subprotocol == publish_auth.PUBLISH_SUBPROTOCOL_V2
    finally:
        await lifecycle.aclose()


@pytest.mark.asyncio
async def test_the_first_mint_starts_the_publisher_and_gets_a_connection(wired):
    store = _Store(live=False)
    lifecycle = wired.build(store)
    await lifecycle.start_if_live()
    assert wired.dials == []
    try:
        async with lifecycle.connected() as publisher:
            assert publisher.connected and publisher.new_link_identity() is not None
            store.live = True
        assert lifecycle.publisher is publisher, "a minted link must keep the connection"
        assert len(wired.built) == 1 and len(wired.dials) == 1
    finally:
        await lifecycle.aclose()


@pytest.mark.asyncio
async def test_two_concurrent_first_mints_share_one_publisher(wired):
    store = _Store(live=False)
    lifecycle = wired.build(store)
    got = []

    async def mint():
        async with lifecycle.connected() as publisher:
            got.append(publisher)
            await asyncio.sleep(0.05)
            store.live = True

    try:
        await asyncio.gather(mint(), mint())
        assert len(wired.built) == 1, f"{len(wired.built)} publishers were built"
        assert len(wired.dials) == 1 and got[0] is got[1]
    finally:
        await lifecycle.aclose()


@pytest.mark.asyncio
async def test_a_publisher_that_does_not_connect_is_refused_and_closed(wired):
    wired.hang = True
    lifecycle = wired.build(_Store(live=False))
    lifecycle._connect_timeout = 0.2
    with pytest.raises(relay_lifecycle.RelayUnavailable) as refused:
        async with lifecycle.connected():
            raise AssertionError("a mint ran on a publisher that never connected")
    assert refused.value.reason == "the relay publisher is not connected"
    await lifecycle._stop_task
    assert lifecycle.publisher is None
    assert wired.built[0]._task.done(), "the dialling loop is still running"


@pytest.mark.asyncio
async def test_the_last_link_going_closes_the_connection_after_an_empty_declaration():
    live = [proto.LinkDeclaration(link_id="lnk_1", token_sha256="ab" * 32,
                                  session_id=SESSION_ID)]
    conn = _FakeConnection()

    async def declarations():
        return list(live)

    async def credentials():
        return publish_auth.LegacyAuth("t")

    def start():
        publisher = relay_publisher.RelayPublisher(
            url="wss://relay.test/publish", credentials=credentials,
            registry=_registry(), declarations=declarations,
            connector=lambda url, dial: conn, refresh_seconds=30.0)
        publisher.start()
        return publisher

    async def has_live_links():
        return bool(live)

    lifecycle = relay_lifecycle.RelayLifecycle(start=start, has_live_links=has_live_links)
    await lifecycle.start_if_live()
    publisher = lifecycle.publisher
    assert await _until(lambda: any('"lnk_1"' in f for f in conn.sent))

    lifecycle.schedule_stop_check()
    await lifecycle._stop_task
    assert lifecycle.publisher is publisher and not conn._closed.is_set()

    live.clear()
    lifecycle.schedule_stop_check()
    await lifecycle._stop_task
    assert lifecycle.publisher is None
    assert conn._closed.is_set(), "the relay connection is still open"
    last = json.loads(conn.sent[-1])
    assert last["type"] == "links" and last["links"] == [], conn.sent[-1]
    assert publisher._task.done()


def test_the_kill_switch_builds_nothing():
    assert relay_lifecycle.build(
        RelayConfig(enabled=False), registry=_Tripwire(), store=_Tripwire()) is None


@pytest.mark.asyncio
async def test_a_final_state_stays_and_is_not_redialled():
    from tests.test_relay_identity import _ClosingConnection

    async def credentials():
        return publish_auth.LegacyAuth("t")

    async def declarations():
        return []

    starts = []

    def start():
        publisher = relay_publisher.RelayPublisher(
            url="wss://relay.test/publish", credentials=credentials,
            registry=_registry(), declarations=declarations,
            connector=lambda url, dial: _ClosingConnection(4403))
        publisher.start()
        starts.append(publisher)
        return publisher

    live = [True]

    async def has_live_links():
        return live[0]

    lifecycle = relay_lifecycle.RelayLifecycle(start=start, has_live_links=has_live_links)
    await lifecycle.start_if_live()
    assert await _until(lambda: starts[0].stopped)
    live[0] = False
    for _ in range(2):
        with pytest.raises(relay_lifecycle.RelayUnavailable) as refused:
            async with lifecycle.connected():
                raise AssertionError("minted on a revoked device")
        assert refused.value.reason == "relay access revoked"
        await lifecycle._stop_task
    assert len(starts) == 1 and lifecycle.publisher is starts[0]
    assert lifecycle.available is False
    await lifecycle.aclose()


@pytest.mark.asyncio
async def test_an_install_that_cannot_build_a_publisher_is_not_available():
    lifecycle = relay_lifecycle.RelayLifecycle(
        start=lambda: None, has_live_links=lambda: asyncio.sleep(0, False))
    assert lifecycle.available is True
    with pytest.raises(relay_lifecycle.RelayUnavailable) as refused:
        async with lifecycle.connected():
            raise AssertionError("minted with no publisher")
    assert refused.value.reason == relay_lifecycle.NOT_RUNNING
    assert lifecycle.available is False


@pytest.mark.asyncio
async def test_a_stop_asked_for_during_a_check_is_not_dropped():
    gate = asyncio.Event()
    live = [True]
    reads = []

    async def has_live_links():
        reads.append(live[0])
        if len(reads) == 1:
            await gate.wait()
        return reads[-1]

    class _Pub:
        stopped = False
        connected = True
        closed = False

        async def aclose(self, **kw):
            self.closed = True

    pub = _Pub()
    lifecycle = relay_lifecycle.RelayLifecycle(start=lambda: pub, has_live_links=has_live_links)
    lifecycle._publisher = pub
    lifecycle.schedule_stop_check()
    await asyncio.sleep(0)
    live[0] = False
    lifecycle.schedule_stop_check()
    gate.set()
    await lifecycle._stop_task
    assert pub.closed and lifecycle.publisher is None
