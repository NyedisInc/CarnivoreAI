
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import tempfile

import pytest
import structlog

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_relaypub_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_relaypub_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config.relay import RelayConfig
from src.core import relay_protocol as proto
from src.core import relay_e2ee, relay_keychain, relay_publisher
from src.core.relay_identity import publish_auth
from src.core.sessions.registry import SessionRegistry
from src.models import Session
from tests.test_spectator_scrub import CHUNK, MARKER, STARRED, _StarringRedactor

pytestmark = pytest.mark.real_relay_start

SESSION_ID = "ses_relay_probe"
FAKE_PUBLISH_TOKEN = "relay-test-token-not-a-secret-7f3a91"
SHARE_TOKEN = "share-token-never-leaves-the-mac"
DECL = proto.LinkDeclaration(
    link_id="lnk_1",
    token_sha256=hashlib.sha256(SHARE_TOKEN.encode()).hexdigest(),
    session_id=SESSION_ID,
)


def _legacy(token: str = FAKE_PUBLISH_TOKEN):
    auth = publish_auth.LegacyAuth(token)

    async def credentials():
        return auth

    return credentials


class _Tripwire:

    def __getattr__(self, name):
        raise AssertionError(f"relay publishing touched {name!r} while off")


class _FakeConnection:

    def __init__(self, hang: bool = False) -> None:
        self.sent: list[str] = []
        self._hang = hang
        self._closed = asyncio.Event()
        self.incoming: asyncio.Queue = asyncio.Queue()

    async def recv(self) -> str:
        return await self.incoming.get()

    async def send(self, text: str) -> None:
        if self._hang:
            await asyncio.Event().wait()
        self.sent.append(text)

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        self._closed.set()


def _registry() -> SessionRegistry:
    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(Session(id=SESSION_ID, working_dir="/tmp"), None)
    return registry


async def _until(predicate, budget: float = 3.0) -> bool:
    deadline = asyncio.get_running_loop().time() + budget
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()




def test_on_by_default_so_a_fresh_install_can_share():
    from src.config.auth import AuthConfig
    from src.config.relay import DEFAULT_RELAY_PUBLISH_URL

    for cfg in (RelayConfig(), AuthConfig.model_fields["relay"].default_factory()):
        assert cfg.enabled is True
        assert cfg.url == DEFAULT_RELAY_PUBLISH_URL == "wss://relay.carnivore.ai/publish"


def test_an_explicit_false_builds_nothing_and_touches_nothing(monkeypatch):
    monkeypatch.setenv(proto.TOKEN_ENVS[0], FAKE_PUBLISH_TOKEN)
    assert relay_publisher.start_if_enabled(
        RelayConfig(enabled=False), registry=_Tripwire(), store=_Tripwire()) is None


def test_enabled_without_a_token_or_over_plain_ws_still_builds_nothing(monkeypatch):
    for name in proto.TOKEN_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(relay_keychain, "read_publish_token", lambda: None)
    assert relay_publisher.start_if_enabled(
        RelayConfig(enabled=True), registry=_Tripwire(), store=_Tripwire()) is None
    monkeypatch.setenv(proto.TOKEN_ENVS[1], FAKE_PUBLISH_TOKEN)
    assert relay_publisher.start_if_enabled(
        RelayConfig(enabled=True, url="ws://plain.example/publish"),
        registry=_Tripwire(), store=_Tripwire()) is None


def _load_relay(tmp_path, body):
    from src.config import auth_loader

    path = tmp_path / "config.json"
    path.write_text(json.dumps(body))
    return auth_loader.load(path, totp_secret="t", jwt_secret="j").relay


def test_the_loader_reads_the_relay_block_from_config_json(tmp_path):
    loaded = _load_relay(tmp_path, {"relay": {
        "enabled": True, "url": "wss://relay.example.test/publish"}})
    assert loaded.enabled is True
    assert loaded.url == "wss://relay.example.test/publish"


def test_an_absent_block_loads_enabled(tmp_path):
    for body in ({}, {"relay": None}, {"relay": {}}):
        loaded = _load_relay(tmp_path, body)
        assert loaded.enabled is True, body
        assert loaded.url == "wss://relay.carnivore.ai/publish"


@pytest.mark.parametrize("body", [
    {"relay": {"enabled": False}},
    {"relay": False},
    {"relay": {"enabled": False, "idle_flush_ms": 0}},
    {"relay": {"enabled": False, "url": ["not", "a", "string"]}},
    {"relay": {"enabled": "false", "idle_flush_ms": 0}},
    {"relay": {"enabled": 0, "idle_flush_ms": 0}},
    {"relay": {"enabled": "off", "idle_flush_ms": 0}},
    {"relay": 0},
    {"relay": "off"},
    {"relay": "garbage"},
    {"relay": {"enabled": "maybe"}},
])
def test_an_explicit_false_loads_disabled(tmp_path, body):
    assert _load_relay(tmp_path, body).enabled is False




def test_the_publish_token_is_never_written_into_config(monkeypatch, tmp_path):
    from src.config.auth import AuthConfig
    from src.core import config_writer

    monkeypatch.setenv(proto.TOKEN_ENVS[1], FAKE_PUBLISH_TOKEN)
    block = RelayConfig.model_validate({"enabled": True, "publish_token": FAKE_PUBLISH_TOKEN})
    path = tmp_path / "config.json"
    path.write_text("{}")
    config_writer.commit(path, lambda data: {**data, "relay": block.model_dump()})

    assert proto.publish_token() == FAKE_PUBLISH_TOKEN
    assert FAKE_PUBLISH_TOKEN not in path.read_text()
    assert not [f for f in RelayConfig.model_fields if "token" in f or "secret" in f]
    assert FAKE_PUBLISH_TOKEN not in json.dumps(
        AuthConfig.model_fields["relay"].default_factory().model_dump())




def test_the_token_resolves_carnivore_env_then_cloude_env_then_keychain(monkeypatch):
    reads: list[str] = []

    def keychain() -> str:
        reads.append("keychain")
        return "from-keychain"

    env = {"CARNIVORE_RELAY_PUBLISH_TOKEN": "from-carnivore",
           "CLOUDE_RELAY_PUBLISH_TOKEN": "from-cloude"}
    assert proto.publish_token(env, keychain) == "from-carnivore"
    assert reads == [], "the Keychain was read although the environment answered"

    del env["CARNIVORE_RELAY_PUBLISH_TOKEN"]
    assert proto.publish_token(env, keychain) == "from-cloude"
    assert reads == []

    env["CLOUDE_RELAY_PUBLISH_TOKEN"] = "   "
    assert proto.publish_token(env, keychain) == "from-keychain", (
        "a blank variable did not fall through to the Keychain"
    )
    assert proto.publish_token({}, lambda: None) is None
    assert proto.publish_token({}, lambda: "  ") is None


def test_the_default_keychain_reader_is_looked_up_at_call_time(monkeypatch):
    for name in proto.TOKEN_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(relay_keychain, "read_publish_token", lambda: "patched")
    assert proto.publish_token() == "patched"


def test_the_production_keychain_item_is_refused_under_test(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(relay_keychain.subprocess, "run",
                        lambda argv, **_: calls.append(argv))
    assert relay_keychain.read_publish_token() is None
    with pytest.raises(relay_keychain.KeychainWriteError):
        relay_keychain.store_publish_token("abc")
    assert calls == [], f"security was run for the production item: {calls!r}"


def test_a_keychain_write_puts_the_secret_on_stdin_never_in_argv(monkeypatch):
    seen: list[dict] = []

    def run(argv, **kwargs):
        seen.append({"argv": argv, **kwargs})
        return relay_keychain.subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(relay_keychain.subprocess, "run", run)
    relay_keychain.write_password("ai.carnivore.test.svc", "acct", "s3cr3t-Tok_en=")
    (call,) = seen
    assert call["argv"] == [relay_keychain.SECURITY_BIN, "-i"]
    assert "s3cr3t-Tok_en=" in call["input"]
    assert " -A" not in call["input"]
    assert all("s3cr3t" not in part for part in call["argv"])

    with pytest.raises(relay_keychain.KeychainWriteError):
        relay_keychain.write_password("ai.carnivore.test.svc", "acct", 'a" -A "b')
    assert len(seen) == 1, "an unsafe secret still reached security"


@pytest.mark.skipif(sys.platform != "darwin" or not os.path.exists("/usr/bin/security"),
                    reason="needs the macOS security binary")
def test_a_real_keychain_round_trip_under_a_throwaway_service():
    import secrets

    service = f"ai.carnivore.test.relay-roundtrip-{secrets.token_hex(4)}"
    try:
        assert relay_keychain.read_password(service, "carnivore") is None
        relay_keychain.write_password(service, "carnivore", "first-Value_1=")
        assert relay_keychain.read_password(service, "carnivore") == "first-Value_1="
        relay_keychain.write_password(service, "carnivore", "second")
        assert relay_keychain.read_password(service, "carnivore") == "second"
    finally:
        relay_keychain.delete_password(service, "carnivore")
    assert relay_keychain.read_password(service, "carnivore") is None




@pytest.mark.asyncio
async def test_publishes_scrubbed_bytes_under_the_digest_and_bearer(monkeypatch):
    registry = _registry()
    conn = _FakeConnection()
    seen: dict = {}

    def connector(url, dial):
        seen.update(url=url, subprotocol=dial.subprotocol, headers=dial.headers)
        return conn

    async def decls():
        return [DECL]

    publisher = relay_publisher.RelayPublisher(
        url="wss://relay.test/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=connector, redactor_factory=_StarringRedactor,
        refresh_seconds=0.05,
    )
    assert publisher.connected is False, "connected before any dial"
    with structlog.testing.capture_logs() as captured:
        publisher.start()
        assert await _until(lambda: len(conn.sent) >= 1)
        assert publisher.connected is True
        registry.publish(SESSION_ID, CHUNK)
        assert await _until(lambda: any('"data"' in f for f in conn.sent))
        await publisher.aclose()
    assert publisher.connected is False, "still connected after the loop ended"

    first = json.loads(conn.sent[0])
    assert re.fullmatch(r"[0-9a-f]{32}", first.pop("publisher_id"))
    assert first == {"type": "links", "links": [
        {"link_id": "lnk_1", "token_sha256": DECL.token_sha256, "session_id": SESSION_ID}]}
    payload = "".join(json.loads(f)["payload"] for f in conn.sent if '"data"' in f)
    assert MARKER in CHUNK.decode()
    assert MARKER not in payload and STARRED.decode() in payload, payload
    assert not any(SHARE_TOKEN in f for f in conn.sent)
    assert seen == {"url": "wss://relay.test/publish", "subprotocol": proto.PUBLISH_SUBPROTOCOL,
                    "headers": {"Authorization": f"Bearer {FAKE_PUBLISH_TOKEN}"}}
    assert not any(FAKE_PUBLISH_TOKEN in str(v) for e in captured for v in e.values())


def test_the_default_dial_sends_the_bearer_header_and_subprotocol(monkeypatch):
    import websockets.asyncio.client as client

    recorded: dict = {}
    monkeypatch.setattr(client, "connect", lambda url, **kw: recorded.update(url=url, **kw))
    relay_publisher._default_connector("wss://relay.test/publish", publish_auth.Dial(
        proto.PUBLISH_SUBPROTOCOL, {"Authorization": f"Bearer {FAKE_PUBLISH_TOKEN}"}))
    assert recorded["subprotocols"] == [proto.PUBLISH_SUBPROTOCOL]
    assert recorded["additional_headers"] == {"Authorization": f"Bearer {FAKE_PUBLISH_TOKEN}"}


@pytest.mark.asyncio
async def test_a_poke_declares_links_well_under_the_refresh_interval():
    registry = _registry()
    conn = _FakeConnection()
    live: list = []

    async def decls():
        return list(live)

    publisher = relay_publisher.RelayPublisher(
        url="wss://r/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=lambda u, t: conn,
        redactor_factory=_StarringRedactor, refresh_seconds=120.0,
    )
    publisher.start()
    assert await _until(lambda: len(conn.sent) >= 1)
    assert json.loads(conn.sent[0])["links"] == []

    live.append(DECL)
    publisher.poke()
    assert await _until(lambda: len(conn.sent) >= 2, budget=1.0), (
        "no second links frame arrived well under the 120s refresh interval"
    )
    await publisher.aclose()
    assert json.loads(conn.sent[-1])["links"] == [
        {"link_id": "lnk_1", "token_sha256": DECL.token_sha256,
         "session_id": SESSION_ID}]


@pytest.mark.asyncio
async def test_a_poke_during_a_pass_is_not_lost():
    registry = _registry()
    conn = _FakeConnection()
    calls: list = []

    async def decls():
        calls.append(asyncio.get_running_loop().time())
        if len(calls) == 1:
            publisher.poke()
        return []

    publisher = relay_publisher.RelayPublisher(
        url="wss://r/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=lambda u, t: conn,
        redactor_factory=_StarringRedactor, refresh_seconds=120.0,
    )
    publisher.start()
    assert await _until(lambda: len(calls) >= 2, budget=1.0), (
        "a poke that landed mid-pass was lost; the next pass waited the refresh"
    )
    await publisher.aclose()
    assert calls[1] - calls[0] < 1.0


@pytest.mark.asyncio
async def test_a_link_leaving_the_live_set_is_undeclared_and_unsubscribed():
    registry = _registry()
    conn = _FakeConnection()
    live = [DECL]

    async def decls():
        return list(live)

    publisher = relay_publisher.RelayPublisher(
        url="wss://r/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=lambda u, t: conn,
        redactor_factory=_StarringRedactor, refresh_seconds=0.05,
    )
    publisher.start()
    assert await _until(lambda: len(registry.subscribers.get(SESSION_ID, [])) == 1)
    live.clear()
    assert await _until(lambda: json.loads(conn.sent[-1]).get("links") == [])
    assert await _until(lambda: not registry.subscribers.get(SESSION_ID))
    await publisher.aclose()


@pytest.mark.asyncio
async def test_a_link_with_no_redactor_is_never_declared():
    registry = _registry()
    conn = _FakeConnection()

    def broken():
        raise ValueError("no redactor")

    async def decls():
        return [DECL]

    publisher = relay_publisher.RelayPublisher(
        url="wss://r/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=lambda u, t: conn,
        redactor_factory=broken, refresh_seconds=0.05,
    )
    publisher.start()
    assert await _until(lambda: len(conn.sent) >= 1)
    registry.publish(SESSION_ID, CHUNK)
    await asyncio.sleep(0.2)
    await publisher.aclose()
    assert json.loads(conn.sent[0])["links"] == []
    assert not any('"data"' in f for f in conn.sent)




def test_backoff_starts_at_two_seconds_doubles_and_caps_at_sixty():
    assert proto.backoff_delay(0, rng=lambda: 0.0) == 2.0
    assert proto.backoff_delay(0, rng=lambda: 0.999) < 2.5
    assert proto.backoff_delay(1, rng=lambda: 0.0) == 4.0
    assert proto.backoff_delay(30, rng=lambda: 0.999) == 60.0


@pytest.mark.asyncio
async def test_a_refused_connection_backs_off_and_retries():
    waits: list[float] = []
    attempts: list[int] = []

    def refusing(url, dial):
        attempts.append(1)
        raise OSError("connection refused")

    async def sleep(seconds):
        waits.append(seconds)
        await asyncio.sleep(0)

    async def decls():
        return []

    publisher = relay_publisher.RelayPublisher(
        url="wss://r/publish", credentials=_legacy(), registry=_registry(),
        declarations=decls, connector=refusing, sleep=sleep,
    )
    publisher.start()
    assert await _until(lambda: len(waits) >= 4)
    assert publisher.connected is False, "a refused dial reads as connected"
    await publisher.aclose()
    assert 2.0 <= waits[0] <= 2.5 and 4.0 <= waits[1] <= 5.0 and 8.0 <= waits[2] <= 10.0
    assert len(attempts) >= 4


@pytest.mark.asyncio
async def test_a_hung_relay_never_costs_the_owner_a_byte():
    registry = _registry()
    owner = registry.subscribe(SESSION_ID)

    async def decls():
        return [DECL]

    publisher = relay_publisher.RelayPublisher(
        url="wss://r/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=lambda u, t: _FakeConnection(hang=True),
        redactor_factory=_StarringRedactor, refresh_seconds=0.05,
        sleep=lambda s: asyncio.sleep(0.01),
    )
    received: list[bytes] = []
    with structlog.testing.capture_logs() as captured:
        publisher.start()
        assert await _until(lambda: len(registry.subscribers.get(SESSION_ID, [])) == 2)
        for i in range(600):
            chunk = CHUNK + str(i).encode()
            registry.publish(SESSION_ID, chunk)
            frame = await owner.get()
            received.append(base64.b64decode(frame.payload))
            await asyncio.sleep(0)
        dropped = await _until(lambda: any(
            e.get("event") == "relay_publish_disconnected" for e in captured))
        await publisher.aclose()

    assert received == [CHUNK + str(i).encode() for i in range(600)]
    assert not owner.closed
    assert dropped, "the hung relay never ended the publisher's connection"




class _PaneBackend:

    def __init__(self, size=(170, 50)) -> None:
        self.size = size
        self.captures = 0

    async def pane_geometry(self):
        return self.size

    def pane_in_alternate_screen(self) -> bool:
        return True

    def capture_visible_screen(self) -> bytes:
        self.captures += 1
        return CHUNK

    def session_age_seconds(self):
        return None


def _frames(conn, kind):
    return [json.loads(f) for f in conn.sent if json.loads(f).get("type") == kind]


@pytest.mark.asyncio
async def test_size_then_a_scrubbed_paint_on_declare_on_join_and_on_resize(monkeypatch):
    monkeypatch.setattr(relay_publisher, "GEOMETRY_POLL_SECONDS", 0.05)
    registry = SessionRegistry(log_cap=lambda: 1000)
    backend = _PaneBackend()
    registry.register(Session(id=SESSION_ID, working_dir="/tmp"), backend)
    conn = _FakeConnection()

    async def decls():
        return [DECL]

    publisher = relay_publisher.RelayPublisher(
        url="wss://relay.test/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=lambda u, d: conn,
        redactor_factory=_StarringRedactor, refresh_seconds=0.05, idle_flush_seconds=0.02,
    )
    publisher.start()
    try:
        assert await _until(lambda: backend.captures >= 1 and any(
            STARRED.decode() in f["payload"] for f in _frames(conn, "data")))
        types = [json.loads(f)["type"] for f in conn.sent]
        assert types.index("links") < types.index("size") < types.index("data")
        assert _frames(conn, "size")[0] == {"type": "size", "link_id": "lnk_1",
                                            "cols": 170, "rows": 50}
        conn.incoming.put_nowait(json.dumps({"type": "joined", "link_id": "lnk_1"}))
        assert await _until(lambda: backend.captures >= 2 and len(_frames(conn, "size")) >= 2)
        conn.incoming.put_nowait(json.dumps({"type": "joined", "link_id": "other"}))
        backend.size = (90, 30)
        assert await _until(lambda: any(f["cols"] == 90 for f in _frames(conn, "size")))
        assert await _until(lambda: "".join(
            f["payload"] for f in _frames(conn, "data")).count(STARRED.decode()) >= 3)
    finally:
        await publisher.aclose()
    payload = "".join(f["payload"] for f in _frames(conn, "data"))
    assert MARKER in CHUNK.decode()
    assert MARKER not in payload
    assert payload.count(STARRED.decode()) >= 3


@pytest.mark.asyncio
async def test_an_unreadable_grid_sends_no_size_and_no_paint():
    registry = SessionRegistry(log_cap=lambda: 1000)
    backend = _PaneBackend(size=None)
    registry.register(Session(id=SESSION_ID, working_dir="/tmp"), backend)
    conn = _FakeConnection()

    async def decls():
        return [DECL]

    publisher = relay_publisher.RelayPublisher(
        url="wss://relay.test/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=lambda u, d: conn,
        redactor_factory=_StarringRedactor, refresh_seconds=0.05,
    )
    publisher.start()
    try:
        assert await _until(lambda: len(conn.sent) >= 3)
        await asyncio.sleep(0.2)
    finally:
        await publisher.aclose()
    assert _frames(conn, "size") == [] and backend.captures == 0


def test_a_paint_is_split_under_the_relay_frame_cap_never_inside_a_character():
    data = ("a" + "é" * 30000).encode()
    pieces = relay_e2ee.utf8_pieces(data, relay_e2ee.MAX_BODY_BYTES)
    assert len(pieces) > 1 and b"".join(pieces) == data
    for piece in pieces:
        assert len(piece) <= relay_e2ee.MAX_BODY_BYTES
        piece.decode("utf-8")
    assert relay_e2ee.utf8_pieces(b"", 16) == []


@pytest.mark.asyncio
async def test_a_burst_of_joins_is_one_paint_and_stale_output_is_not_replayed(monkeypatch):
    monkeypatch.setattr(relay_publisher, "GEOMETRY_POLL_SECONDS", 30.0)
    monkeypatch.setattr(relay_publisher, "MIN_PAINT_INTERVAL_SECONDS", 0.5)
    registry = SessionRegistry(log_cap=lambda: 1000)
    backend = _PaneBackend()
    registry.register(Session(id=SESSION_ID, working_dir="/tmp"), backend)
    conn = _FakeConnection()

    async def decls():
        return [DECL]

    publisher = relay_publisher.RelayPublisher(
        url="wss://relay.test/publish", credentials=_legacy(), registry=registry,
        declarations=decls, connector=lambda u, d: conn,
        redactor_factory=_StarringRedactor, refresh_seconds=0.05, idle_flush_seconds=0.02,
    )
    publisher.start()
    try:
        assert await _until(lambda: backend.captures == 1)
        joined = json.dumps({"type": "joined", "link_id": "lnk_1"})
        for _ in range(5):
            conn.incoming.put_nowait(joined)
        await asyncio.sleep(0.2)
        assert backend.captures == 1, "joins inside the interval painted at once"
        assert await _until(lambda: backend.captures == 2)
        await asyncio.sleep(0.6)
        assert backend.captures == 2, "a burst of joins is one paint"
    finally:
        await publisher.aclose()


@pytest.mark.asyncio
async def test_output_queued_before_a_paint_is_not_replayed_after_it():
    from src.core import spectator_redaction, viewer_fanout

    registry = SessionRegistry(log_cap=lambda: 1000)
    backend = _PaneBackend()
    registry.register(Session(id=SESSION_ID, working_dir="/tmp"), backend)
    stream = registry.subscribe(SESSION_ID)
    registry.publish(SESSION_ID, b"STALE-BEFORE-CAPTURE")
    outbox = viewer_fanout.new_viewer_stream("test outbox")
    scrubber = spectator_redaction.build_scrubber(
        label="lnk_1", factory=_StarringRedactor, idle_flush_seconds=0.02)
    repaint = asyncio.Event()
    repaint.set()
    pump = asyncio.create_task(relay_publisher._pump(
        "lnk_1", stream, scrubber, outbox, lambda: backend, repaint))
    sent: list = []
    try:
        while True:
            frame = await asyncio.wait_for(outbox.get(), 0.5)
            sent.append(json.loads(frame.payload))
    except asyncio.TimeoutError:
        pass
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        registry.unsubscribe(stream, SESSION_ID)
    assert sent and sent[0]["type"] == "size"
    payload = "".join(f.get("payload", "") for f in sent)
    assert STARRED.decode() in payload
    assert "STALE-BEFORE-CAPTURE" not in payload
