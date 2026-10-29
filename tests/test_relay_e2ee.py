
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

import pytest
import structlog
from starlette.websockets import WebSocketDisconnect

from relay.bounded import REFUSED_CLOSE_CODE
from relay.hub import RelayHub
from relay.protocol import LinkDeclaration, parse_record_frame
from src.core import relay_e2ee
from src.core import relay_protocol as proto
from src.core import relay_publisher
from src.core.relay_identity import publish_auth
from src.core.relay_link_framer import current_scrubber_id
from src.core.sessions.registry import SessionRegistry
from src.core.spectator_links_store import (
    LinkKeysUnavailableError,
    SpectatorLinksStore,
    link_token_db_path,
)
from src.core.spectator_redaction import Scrubbed
from src.models import Session
from tests.relay_support import RecordingFactory, data_frame
from tests.relay_v2_support import (
    V2_TOKEN,
    Device,
    Issuer,
    SealedLink,
    links_v2,
    scrubbed,
    watch_v2,
)
from tests.test_relay_sockets import build_settings, relay, wait_for_links
from tests.test_relay_v2_sockets import closed_with, connect

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "relay_e2ee_vectors.json").read_text())

SECRET = "ghp_" + "Ab3dE5gH7jK9mN1pQ3sT5vW7yZ0bC2eF4hJ6"
SESSION_ID = "ses_e2ee_probe"


def _rfc5869(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()


def _split(frame: bytes) -> tuple:
    size = frame[0]
    return frame[1:1 + size].decode(), frame[1 + size:]




def test_the_known_answer_vectors_match():
    token, link_id = VECTORS["token"], VECTORS["link_id"]
    keys = relay_e2ee.derive_link_keys(token, link_id)
    ikm = relay_e2ee.token_bytes(token)
    assert keys.watch_auth == _rfc5869(ikm, link_id.encode(), b"carnivore relay v2 watch-auth")
    assert keys.content_key == _rfc5869(ikm, link_id.encode(), b"carnivore relay v2 content-key")
    assert relay_e2ee.b64url(keys.watch_auth) == VECTORS["watch_auth_b64url"]
    assert keys.verifier == VECTORS["verifier_hex"] == hashlib.sha256(keys.watch_auth).hexdigest()
    assert keys.content_key.hex() == VECTORS["content_key_hex"]
    stream_id = bytes.fromhex(VECTORS["stream_id_hex"])
    stream_key = relay_e2ee.stream_key(keys.content_key, stream_id)
    assert stream_key == _rfc5869(keys.content_key, stream_id, b"carnivore relay v2 stream-key")
    assert stream_key.hex() == VECTORS["stream_key_hex"]
    assert relay_e2ee.share_fragment(token, True) == VECTORS["fragment"]
    for vec in VECTORS["records"]:
        body = bytes.fromhex(vec["body_hex"])
        record = relay_e2ee.seal_record(keys.content_key, link_id, stream_id, vec["seq"],
                                        vec["kind"], vec["ts_ms"], body)
        assert record.hex() == vec["record_hex"]
        assert relay_e2ee.record_aad(link_id, stream_id, vec["seq"]).hex() == vec["aad_hex"]
        opened = relay_e2ee.open_record(keys.content_key, link_id, record)
        assert (opened.seq, opened.kind, opened.ts_ms, opened.body) == (
            vec["seq"], vec["kind"], vec["ts_ms"], body)


@pytest.mark.parametrize("offset,label", [(0, "ver"), (5, "stream_id"), (24, "seq"),
                                          (30, "ciphertext"), (-1, "tag")])
def test_a_bit_flipped_in_any_field_fails(offset, label):
    keys = relay_e2ee.derive_link_keys(VECTORS["token"], VECTORS["link_id"])
    record = bytearray(bytes.fromhex(VECTORS["records"][2]["record_hex"]))
    relay_e2ee.open_record(keys.content_key, VECTORS["link_id"], bytes(record))
    record[offset] ^= 0x01
    with pytest.raises(relay_e2ee.E2eeError):
        relay_e2ee.open_record(keys.content_key, VECTORS["link_id"], bytes(record))


def test_a_record_moved_to_another_link_fails():
    key = bytes(range(32))
    record = relay_e2ee.seal_record(key, "linkA", bytes(16), 3, relay_e2ee.KIND_DATA, 1, b"x")
    assert relay_e2ee.open_record(key, "linkA", record).body == b"x"
    with pytest.raises(relay_e2ee.E2eeError):
        relay_e2ee.open_record(key, "linkB", record)


@pytest.mark.parametrize("token", [*VECTORS["wrong_length_tokens"],
                                   VECTORS["token"] + "=", VECTORS["token"][:-1] + "9",
                                   "", "not base64 !"])
def test_a_token_that_is_not_exactly_32_bytes_is_refused(token):
    with pytest.raises(relay_e2ee.E2eeError):
        relay_e2ee.derive_link_keys(token, "l")


def test_only_a_scrubbers_output_can_be_sealed():
    sealer = relay_e2ee.Sealer("l", bytes(32))
    sealer.open(expires_at=1, scrubber="0" * 12, client_version="x", cols=1, rows=1)
    with pytest.raises(TypeError):
        sealer.data(b"raw pane bytes")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        sealer.paint(bytearray(b"raw"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Scrubbed(b"forged")
    ok = scrubbed(b"released")
    with pytest.raises(TypeError):
        sealer.data(ok[1:])
    assert len(sealer.data(ok)) == 1


def test_every_stream_has_its_own_key_and_seq_never_repeats():
    sealer = relay_e2ee.Sealer("l", bytes(32))
    first = sealer.open(expires_at=1, scrubber="0" * 12, client_version="x", cols=1, rows=1)
    records = [first, *sealer.data(scrubbed(b"a")), sealer.beat()]
    second = sealer.open(expires_at=1, scrubber="0" * 12, client_version="x", cols=1, rows=1)
    headers = [(r[1:17], r[17:25]) for r in records]
    assert len(set(headers)) == len(headers)
    assert [int.from_bytes(s, "big") for _, s in headers] == [0, 1, 2]
    assert second[1:17] != first[1:17] and second[17:25] == bytes(8)


def test_each_open_names_the_stream_it_replaces_and_its_last_seq():
    key = bytes(range(32))
    sealer = relay_e2ee.Sealer("l", key)
    first = sealer.open(expires_at=1, scrubber="0" * 12, client_version="x", cols=1, rows=1)
    sealer.data(scrubbed(b"a"))
    sealer.beat()
    second = sealer.open(expires_at=1, scrubber="0" * 12, client_version="x", cols=1, rows=1)
    assert json.loads(relay_e2ee.open_record(key, "l", first).body)["prev"] is None
    assert json.loads(relay_e2ee.open_record(key, "l", second).body)["prev"] == {
        "stream": first[1:17].hex(), "seq": 2}


def test_an_unreadable_grid_still_renews_the_stream_at_the_last_measured_grid():
    from src.core.relay_link_framer import SealedFramer
    key = bytes(range(32))
    framer = SealedFramer("l", key, expires_at=1, client_version="x")
    assert framer.reopen() == []
    framer.grid(120, 40)
    (frame,) = framer.reopen()
    opened = relay_e2ee.open_record(key, "l", _split(frame)[1])
    assert (opened.kind, opened.seq) == (relay_e2ee.KIND_OPEN, 0)
    assert (json.loads(opened.body)["cols"], json.loads(opened.body)["rows"]) == (120, 40)


def test_link_keys_never_print_their_bytes():
    keys = relay_e2ee.derive_link_keys(VECTORS["token"], VECTORS["link_id"])
    text = repr(keys)
    assert keys.content_key.hex() not in text and repr(keys.content_key) not in text
    assert repr(keys.watch_auth) not in text


def test_the_scrubber_id_is_the_sorted_detector_and_redactor_sources():
    core = Path(relay_e2ee.__file__).resolve().parent
    digest = hashlib.sha256()
    names = sorted([*core.glob("message_model_secret*.py"), *core.glob("stream_redactor*.py")],
                   key=lambda p: p.name)
    assert len(names) >= 5
    for path in names:
        digest.update(path.name.encode() + b"\x00" + path.read_bytes() + b"\x00")
    assert relay_e2ee.scrubber_id() == digest.hexdigest()[:12] == current_scrubber_id()




class _V2Auth:

    version = 2

    async def dial(self):
        return publish_auth.Dial(publish_auth.PUBLISH_SUBPROTOCOL_V2, {})

    def declarable(self, decl) -> bool:
        return decl.content_key is not None

    def links_frame(self, decls, publisher_id) -> str:
        return publish_auth.DeviceAuth.links_frame(self, decls, publisher_id)  # type: ignore[arg-type]

    def reauth_due(self) -> bool:
        return False

    def invalidate(self) -> None:
        pass


class _Conn:

    def __init__(self) -> None:
        self.sent: list = []
        self.incoming: asyncio.Queue = asyncio.Queue()
        self._closed = asyncio.Event()

    async def recv(self):
        return await self.incoming.get()

    async def send(self, frame) -> None:
        self.sent.append(frame)

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        self._closed.set()


class _Pane:

    def __init__(self) -> None:
        self.screen = f"visible {SECRET} end-of-screen\r\n".encode()

    async def pane_geometry(self):
        return (170, 50)

    def pane_in_alternate_screen(self) -> bool:
        return True

    def capture_visible_screen(self) -> bytes:
        return self.screen

    def session_age_seconds(self):
        return None


@pytest.mark.asyncio
async def test_a_secret_in_the_pane_arrives_starred_and_no_frame_carries_t_or_k():
    token = secrets.token_urlsafe(32)
    link_id = "lnkE2EEprobe"
    keys = relay_e2ee.derive_link_keys(token, link_id)
    expires_at = int(time.time()) + 3600
    decl = proto.LinkDeclaration(link_id=link_id, token_sha256=keys.verifier,
                                 session_id=SESSION_ID, nonce="n", expires_at=expires_at,
                                 content_key=keys.content_key)
    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(Session(id=SESSION_ID, working_dir="/tmp"), _Pane())
    conn = _Conn()

    async def credentials():
        return _V2Auth()

    async def decls():
        return [decl]

    publisher = relay_publisher.RelayPublisher(
        url="wss://relay.test/publish", credentials=credentials, registry=registry,
        declarations=decls, connector=lambda u, d: conn, refresh_seconds=0.05,
        idle_flush_seconds=0.05, version="9.9.9")
    publisher.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any(isinstance(f, bytes) for f in conn.sent):
            await asyncio.sleep(0.01)
        registry.publish(SESSION_ID, f"live {SECRET} tail\r\n".encode())
        await asyncio.sleep(0.5)
    finally:
        await publisher.aclose()
    binary = [f for f in conn.sent if isinstance(f, bytes)]
    assert binary, "the publisher sealed nothing"
    opened = []
    for frame in binary:
        routed, record = _split(frame)
        assert routed == link_id
        opened.append(relay_e2ee.open_record(keys.content_key, link_id, record))
    first = opened[0]
    assert (first.kind, first.seq) == (relay_e2ee.KIND_OPEN, 0)
    assert json.loads(first.body) == {
        "client_version": "9.9.9", "cols": 170, "rows": 50, "expires_at": expires_at,
        "prev": None, "scrubber_id": current_scrubber_id()}
    plain = b"".join(r.body for r in opened
                     if r.kind in (relay_e2ee.KIND_DATA, relay_e2ee.KIND_PAINT))
    assert b"visible " in plain and b"live " in plain
    assert SECRET.encode() not in plain and b"****" in plain
    for frame in conn.sent:
        raw = frame if isinstance(frame, bytes) else frame.encode()
        for needle in (token.encode(), keys.content_key, keys.content_key.hex().encode(),
                       relay_e2ee.token_bytes(token), SECRET.encode(), keys.watch_auth):
            assert needle not in raw


def test_the_publishers_scrubber_runs_the_relay_profile():
    from src.core.spectator_redaction import relay_redactor_factory
    assert relay_redactor_factory()._tail_bytes == 2048
    publisher = relay_publisher.RelayPublisher(
        url="wss://r/publish", credentials=None, registry=None, declarations=None)
    assert publisher._factory is relay_redactor_factory




@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


def test_the_relay_forwards_records_byte_for_byte_and_builds_no_redactor(issuer):
    device = Device()
    link_id, nonce = device.link()
    with relay(build_settings(issuer_keys=issuer.pins)) as (client, factory):
        with connect(client, device, issuer.token(device)) as pub:
            pub.send_text(json.dumps(links_v2({link_id: V2_TOKEN}, {link_id: nonce})))
            wait_for_links(client, 1)
            with client.websocket_connect(f"/watch/{link_id}",
                                          subprotocols=watch_v2(link_id)) as viewer:
                sealed = SealedLink(link_id)
                sent = [sealed.open(), *sealed.data("opaque\n")]
                for frame in sent:
                    pub.send_bytes(frame)
                received = [viewer.receive_bytes() for _ in sent]
                assert received == [_split(f)[1] for f in sent]
                pub.send_text(json.dumps(data_frame(link_id, "plaintext")))
                assert closed_with(pub) == 4426
        assert factory.made == []
        assert client.app.state.hub.redactor_for(link_id) is None


def test_the_relay_never_logs_or_holds_t_or_k_and_admits_a_not_t(issuer):
    device = Device()
    link_id, nonce = device.link()
    keys = relay_e2ee.derive_link_keys(V2_TOKEN, link_id)
    needles = [V2_TOKEN, relay_e2ee.b64url(keys.watch_auth), keys.content_key.hex(),
               relay_e2ee.b64url(keys.content_key), "plaintext-marker"]
    with structlog.testing.capture_logs() as logs:
        with relay(build_settings(issuer_keys=issuer.pins)) as (client, _factory):
            with connect(client, device, issuer.token(device)) as pub:
                pub.send_text(json.dumps(links_v2({link_id: V2_TOKEN}, {link_id: nonce})))
                wait_for_links(client, 1)
                with client.websocket_connect(f"/watch/{link_id}",
                                              subprotocols=watch_v2(link_id)) as viewer:
                    sealed = SealedLink(link_id)
                    pub.send_bytes(sealed.open())
                    for frame in sealed.data("plaintext-marker\n"):
                        pub.send_bytes(frame)
                    viewer.receive_bytes()
                    assert b"plaintext-marker" in sealed.read(viewer.receive_bytes()).body
                with pytest.raises(WebSocketDisconnect) as refused:
                    with client.websocket_connect(f"/watch/{link_id}",
                                                  subprotocols=["cloude.relay.watch.v1",
                                                                V2_TOKEN]):
                        pass
                assert refused.value.code == REFUSED_CLOSE_CODE
                state = client.app.state.hub._links[link_id]
                held = [state.declaration.token_sha256, state.latest_open or b""]
                for needle in needles:
                    for value in held:
                        raw = value if isinstance(value, bytes) else value.encode()
                        assert needle.encode() not in raw
                    assert keys.content_key not in (state.latest_open or b"")
    assert logs, "population: the relay logged its events"
    text = json.dumps(logs, default=str)
    for needle in needles:
        assert needle not in text


def test_a_joiner_gets_the_cached_open_then_a_fresh_stream_it_decrypts():
    asyncio.run(_joiner())


async def _joiner() -> None:
    hub = RelayHub(redactor_factory=RecordingFactory(), max_watcher_chunks=64,
                   max_watcher_bytes=1 << 20, idle_flush_ms=50)
    sealed = SealedLink("lnk")
    joins: list = []
    hub.declare("c1", [LinkDeclaration("lnk", sealed.keys.verifier)], publisher_id="sub:a",
                e2ee=True)
    hub.attach_publisher("c1", joins.append)

    def publish(frame: bytes) -> None:
        assert hub.publish_record("c1", parse_record_frame(frame))

    publish(sealed.open(120, 40))
    for frame in sealed.data("old stream\n"):
        publish(frame)
    watcher = hub.add_watcher("lnk")
    assert joins == ["lnk"], "the join asks the publisher for a fresh stream"
    for frame in sealed.data("mid-stream, not for the joiner\n"):
        publish(frame)
    publish(sealed.open(120, 40))
    for frame in sealed.sealer.paint(scrubbed(b"painted screen")):
        publish(relay_e2ee.record_frame("lnk", frame))
    got = []
    watcher.stream.close()
    while (item := await watcher.stream.get()) is not None:
        got.append(sealed.read(item))
    assert [(r.kind, r.seq) for r in got] == [
        (relay_e2ee.KIND_OPEN, 0), (relay_e2ee.KIND_OPEN, 0), (relay_e2ee.KIND_PAINT, 1)]
    assert got[0].stream_id != got[1].stream_id
    assert json.loads(got[1].body)["cols"] == 120 and got[2].body == b"painted screen"
    hub.shutdown()


@pytest.mark.asyncio
async def test_record_bytes_are_charged_to_the_tenant():
    from relay import publish_socket

    charged = []

    class _Tenancy:
        async def consume(self, ten, size, lim):
            charged.append((ten, size))
            return None

    class _Hub:
        def publish_record(self, cid, frame):
            self.frame = frame
            return True

    frame = SealedLink("lnk").open()
    hub = _Hub()
    await publish_socket._apply_record(hub, "c", frame, _Tenancy(), "ten", {})
    assert charged == [("ten", len(_split(frame)[1]))]
    assert hub.frame.record == _split(frame)[1]




@pytest.mark.asyncio
async def test_a_v2_mint_keeps_k_in_the_sidecar_only_and_declares_sha256_of_a(tmp_path):
    db = tmp_path / "cloude.db"
    store = SpectatorLinksStore(str(db))
    await store.init()
    try:
        minted = await store.mint("ses", 600, identity=("derivedLinkId", "bm9uY2U"))
        keys = relay_e2ee.derive_link_keys(minted.token, "derivedLinkId")
        (row,) = await store.live_relay_declarations()
        assert row[2] == keys.verifier and row[5] == keys.content_key
    finally:
        await store.close()
    assert keys.content_key not in db.read_bytes()
    assert keys.content_key.hex().encode() not in db.read_bytes()
    sidecar = link_token_db_path(str(db))
    assert oct(os.stat(sidecar).st_mode & 0o777) == "0o600"
    conn = sqlite3.connect(sidecar)
    assert conn.execute("SELECT content_key FROM spectator_link_tokens").fetchone()[0] == \
        keys.content_key
    conn.close()


@pytest.mark.asyncio
async def test_a_v2_link_minted_before_e2ee_is_revoked_at_init(tmp_path):
    db = tmp_path / "cloude.db"
    store = SpectatorLinksStore(str(db))
    await store.init()
    old = await store.mint("ses_old", 600, identity=("oldDerivedId", "bm9uY2U"))
    plain = await store.mint("ses_v1", 600)
    await store.close()
    sidecar = sqlite3.connect(link_token_db_path(str(db)))
    sidecar.execute("UPDATE spectator_link_tokens SET content_key = NULL WHERE link_id = ?",
                    (old.link.id,))
    sidecar.commit()
    sidecar.close()
    reopened = SpectatorLinksStore(str(db))
    await reopened.init()
    try:
        live = [row[0] for row in await reopened.live_relay_declarations()]
        assert live == [plain.link.id], "the keyless v2 link is gone, the v1 one stays"
        assert (await reopened.get(old.link.id)).revoked_at is not None
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_a_failed_key_write_leaves_the_current_link_live(tmp_path):
    store = SpectatorLinksStore(str(tmp_path / "cloude.db"))
    await store.init()
    try:
        live = await store.mint("ses", 600, identity=("firstDerivedId", "bm9uY2U"))

        async def refuse(*_a, **_k):
            return False

        store._keep_token = refuse
        with pytest.raises(LinkKeysUnavailableError):
            await store.mint("ses", 600, identity=("secondDerivedId", "bm9uY2U"))
        assert [row[0] for row in await store.live_relay_declarations()] == [live.link.id]
        assert await store.get("secondDerivedId") is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_a_v2_mint_whose_key_cannot_be_kept_is_refused(tmp_path):
    store = SpectatorLinksStore(str(tmp_path / "cloude.db"))
    await store.init()
    try:
        await store._tokens.close()
        store._tokens = None
        with pytest.raises(LinkKeysUnavailableError):
            await store.mint("ses", 600, identity=("derivedLinkId", "bm9uY2U"))
        assert await store.live_relay_declarations() == []
        assert (await store.mint("ses", 600)).link.e2ee is False
    finally:
        await store.close()
