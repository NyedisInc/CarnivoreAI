
from __future__ import annotations

import asyncio
import base64
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_relayid_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_relayid_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from relay.auth import ReplayCache, verify_pop, verify_relay_token
from relay.protocol import link_id_v2
from src.core import relay_keychain, relay_publisher
from src.core import relay_protocol as proto
from src.core.catalog import hosted_api
from src.core.relay_identity import device_key as dk
from src.core.relay_identity import publish_auth
from src.core.relay_identity.account import account_id
from src.core.relay_identity.session import (
    META_REGISTERED,
    DeviceSession,
    RelayAuthError,
)
from tests.relay_v2_support import Device, Issuer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hosted" / "relay-control"))
import rc_crypto  # noqa: E402

pytestmark = pytest.mark.real_relay_start


class FakeKeychain:

    def __init__(self, state: str = relay_keychain.READ_ABSENT) -> None:
        self.items: dict = {}
        self.writes = 0
        self.forced = None if state == relay_keychain.READ_ABSENT else state

    def read(self, service, account):
        if self.forced:
            return self.forced, None
        value = self.items.get((service, account))
        return (relay_keychain.READ_OK, value) if value else (relay_keychain.READ_ABSENT, None)

    def write(self, service, account, secret, replace=True):
        self.writes += 1
        if not replace and (service, account) in self.items:
            raise relay_keychain.KeychainWriteError("security exited 0")
        self.items[(service, account)] = secret


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "cloude.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    return path


class FakeControl:

    def __init__(self, issuer: Issuer, token_status: int = 200) -> None:
        self.issuer = issuer
        self.calls: list = []
        self.token_status = token_status
        self.unreachable = 0

    async def __call__(self, base, method, path, *, json_body=None, bearer=None):
        self.calls.append((path, json_body, bearer))
        if self.unreachable:
            self.unreachable -= 1
            raise hosted_api.HostedUnavailable("unavailable", "down")
        if path == "/devices":
            raw = dk.unb64url(json_body["pub"], 32)
            self.device = Device.__new__(Device)
            self.device.pub, self.device.device_id = raw, dk.device_id_for(raw)
            self.device.ten = "A" * 22
            return hosted_api.HostedAnswer(200, {"device_id": self.device.device_id})
        if self.token_status != 200:
            return hosted_api.HostedAnswer(self.token_status, {"code": "x"})
        token = self.issuer.token(self.device)
        exp = json.loads(_payload(token))["exp"]
        return hosted_api.HostedAnswer(200, {"token": token, "exp": exp})


def _payload(token: str) -> bytes:
    body = token.split(".")[1]
    return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))


def _session(tmp_path, control, keychain=None, clock=None) -> DeviceSession:
    keychain = keychain or FakeKeychain()
    return DeviceSession(
        db_path=_db(tmp_path), version="v1.8.1-3-gabc", call=control,
        key_loader=lambda install: dk.load_or_create(install, read=keychain.read,
                                                     write=keychain.write),
        clock=clock or __import__("time").time, sleep=lambda s: asyncio.sleep(0))




def test_an_absent_key_is_minted_once_and_reused():
    keychain = FakeKeychain()
    first = dk.load_or_create("install-1", read=keychain.read, write=keychain.write)
    again = dk.load_or_create("install-1", read=keychain.read, write=keychain.write)
    assert first.device_id == again.device_id and keychain.writes == 1
    assert ("ai.carnivore.relay.device-key", "install-1") in keychain.items
    assert "_private" not in repr(first)


def test_an_unreadable_keychain_fails_closed_and_never_mints():
    keychain = FakeKeychain(relay_keychain.READ_UNAVAILABLE)
    with pytest.raises(dk.DeviceKeyUnavailable):
        dk.load_or_create("install-1", read=keychain.read, write=keychain.write)
    assert keychain.writes == 0


def test_two_racing_mints_end_on_one_key():
    keychain = FakeKeychain()
    real_read = keychain.read
    raced = []

    def read(service, account):
        state = real_read(service, account)
        if not raced:
            raced.append(dk.load_or_create(account, read=real_read, write=keychain.write))
        return state

    ours = dk.load_or_create("i", read=read, write=keychain.write)
    assert ours.device_id == raced[0].device_id
    assert dk.unb64url(keychain.items[(relay_keychain.DEVICE_KEY_SERVICE, "i")], 32)


def test_a_malformed_stored_key_fails_closed_and_is_not_replaced():
    keychain = FakeKeychain()
    keychain.items[(relay_keychain.DEVICE_KEY_SERVICE, "i")] = "not-a-seed"
    with pytest.raises(dk.DeviceKeyUnavailable):
        dk.load_or_create("i", read=keychain.read, write=keychain.write)
    assert keychain.writes == 0


def test_the_production_device_key_item_is_refused_under_test():
    assert relay_keychain.read_password_state(relay_keychain.DEVICE_KEY_SERVICE, "x") == (
        relay_keychain.READ_UNAVAILABLE, None)
    with pytest.raises(relay_keychain.KeychainWriteError):
        relay_keychain.write_password(relay_keychain.DEVICE_KEY_SERVICE, "x", "abc")


def test_a_testsrv_slot_never_shells_out_to_security_for_a_production_item(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        raise AssertionError("security must not be called")

    monkeypatch.setattr(relay_keychain.subprocess, "run", fake_run)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CLOUDE_TEST_MODE", raising=False)
    monkeypatch.setenv(relay_keychain.TEST_SLOT_ENV, "/slot/env")
    for service in (relay_keychain.DEVICE_KEY_SERVICE, relay_keychain.FEDERATION_KEY_SERVICE):
        assert relay_keychain.read_password_state(service, "i") == (relay_keychain.READ_UNAVAILABLE, None)
        with pytest.raises(relay_keychain.KeychainWriteError):
            relay_keychain.write_password(service, "i", "abc")
        assert relay_keychain.delete_password(service, "i") is False
    assert calls == []
    monkeypatch.delenv(relay_keychain.TEST_SLOT_ENV)
    monkeypatch.setattr(relay_keychain.subprocess, "run", lambda argv, **kw: calls.append(argv) or type(
        "R", (), {"returncode": 44, "stdout": "", "stderr": ""})())
    assert relay_keychain.read_password_state(relay_keychain.FEDERATION_KEY_SERVICE, "i")[0] == relay_keychain.READ_ABSENT
    assert len(calls) == 1


def test_a_slot_federation_key_persists_through_a_0600_file_and_never_calls_security(monkeypatch, tmp_path):
    from src.config import settings
    from src.core.federation import fed_key

    def fake_run(argv, **kwargs):
        raise AssertionError("security must not be called")

    monkeypatch.setattr(relay_keychain.subprocess, "run", fake_run)
    monkeypatch.setenv(relay_keychain.TEST_SLOT_ENV, "/slot/env")
    monkeypatch.setattr(settings, "state_dir_override", str(tmp_path))
    first = fed_key.load_key("install-1")
    second = fed_key.load_key("install-1")
    assert first.raw_pub == second.raw_pub
    key_file = tmp_path / fed_key.SLOT_KEY_FILE
    assert key_file.stat().st_mode & 0o777 == 0o600


def test_the_signed_bytes_match_the_control_plane_and_the_relay():
    key = dk.DeviceKey.from_seed(bytes(range(32)))
    assert key.device_id == rc_crypto.device_id_for(key.raw_pub)
    reg = rc_crypto.register_message(key.device_id, key.raw_pub, 1700000000)
    assert rc_crypto.verify_ed25519(key.raw_pub, dk.unb64url(key.sign(
        dk.register_message(key.device_id, key.raw_pub, 1700000000))), reg)
    tok = rc_crypto.token_message(key.device_id, 1700000000, b"\x01" * 16)
    assert dk.token_message(key.device_id, 1700000000, b"\x01" * 16) == tok
    assert dk.link_id_for(key.device_id, b"\x02" * 16) == link_id_v2(key.device_id, b"\x02" * 16)




@pytest.mark.asyncio
async def test_registration_happens_once_and_tokens_are_reused_until_the_margin(tmp_path):
    issuer = Issuer()
    control = FakeControl(issuer)
    now = [__import__("time").time()]
    session = _session(tmp_path, control, clock=lambda: now[0])
    first = await session.token()
    assert await session.token() is first
    assert [c[0] for c in control.calls] == ["/devices", "/token"]
    assert all(c[2] is None for c in control.calls), "a bearer was sent"
    reg = control.calls[0][1]
    assert rc_crypto.verify_ed25519(dk.unb64url(reg["pub"]), dk.unb64url(reg["sig"]),
                                    rc_crypto.register_message(session.device_id,
                                                               dk.unb64url(reg["pub"]), reg["ts"]))
    treq = control.calls[1][1]
    assert treq["client"] == "1.8.1"
    assert rc_crypto.verify_ed25519(dk.unb64url(reg["pub"]), dk.unb64url(treq["sig"]),
                                    rc_crypto.token_message(session.device_id, treq["ts"],
                                                            dk.unb64url(treq["nonce"])))
    now[0] = first.exp - 119
    second = await session.token()
    assert second is not first
    assert [c[0] for c in control.calls] == ["/devices", "/token", "/token"]
    conn = sqlite3.connect(session._db_path)
    assert conn.execute("SELECT value FROM meta WHERE key=?",
                        (META_REGISTERED,)).fetchone()[0] == session.device_id
    control.calls.clear()
    again = DeviceSession(db_path=session._db_path, call=control,
                          key_loader=lambda i: session._key)
    await again.token()
    assert [c[0] for c in control.calls] == ["/token"]


@pytest.mark.asyncio
async def test_the_proof_and_reauth_verify_at_the_relay(tmp_path):
    issuer = Issuer()
    session = _session(tmp_path, FakeControl(issuer))
    token = await session.token()
    headers = await session.pop_headers(token)
    claims = verify_relay_token(headers["Authorization"].split(" ", 1)[1], issuer.pins)
    cache = ReplayCache()
    verify_pop(claims, headers["Carnivore-Relay-PoP-Ts"], headers["Carnivore-Relay-PoP"], cache)
    frame = await session.reauth_frame(token)
    assert frame["type"] == "reauth"
    verify_pop(claims, str(frame["pop_ts"]), frame["pop"], ReplayCache())
    link_id, nonce = session.new_link_identity()
    assert link_id == link_id_v2(session.device_id, dk.unb64url(nonce, 16))


@pytest.mark.asyncio
@pytest.mark.parametrize("status,kind,terminal", [
    (403, "revoked", True), (426, "update_required", True),
    (429, "rate_limited", False), (401, "refused", False)])
async def test_refusals_map_to_kinds(tmp_path, status, kind, terminal):
    session = _session(tmp_path, FakeControl(Issuer(), token_status=status))
    with pytest.raises(RelayAuthError) as refused:
        await session.token()
    assert (refused.value.kind, refused.value.terminal) == (kind, terminal)


@pytest.mark.asyncio
async def test_an_unreachable_control_plane_is_retried_a_bounded_number_of_times(tmp_path):
    control = FakeControl(Issuer())
    control.unreachable = 99
    session = _session(tmp_path, control)
    with pytest.raises(RelayAuthError) as refused:
        await session.token()
    assert refused.value.kind == "control_unreachable"
    assert len(control.calls) == 3
    control.unreachable = 2
    assert await session.token()


@pytest.mark.asyncio
async def test_a_locked_keychain_is_keychain_unavailable(tmp_path):
    session = _session(tmp_path, FakeControl(Issuer()),
                       keychain=FakeKeychain(relay_keychain.READ_UNAVAILABLE))
    with pytest.raises(RelayAuthError) as refused:
        await session.token()
    assert refused.value.kind == "keychain_unavailable" and not refused.value.terminal




@pytest.mark.asyncio
async def test_a_revoked_device_never_falls_back_to_the_shared_token(tmp_path):
    session = _session(tmp_path, FakeControl(Issuer(), token_status=403))
    with pytest.raises(RelayAuthError) as refused:
        await publish_auth.resolve(session, lambda: "legacy-token")
    assert refused.value.kind == "revoked"


@pytest.mark.asyncio
async def test_the_fallback_never_carries_an_e2ee_link(tmp_path):
    control = FakeControl(Issuer())
    session = _session(tmp_path, control)
    await session.key()
    control.unreachable = 99
    auth = await publish_auth.resolve(session, lambda: "legacy-token")
    assert isinstance(auth, publish_auth.LegacyAuth)
    assert auth.new_link_identity() is None
    link_id, nonce = session.new_link_identity()
    v2_link = proto.LinkDeclaration(link_id=link_id, token_sha256="a" * 64,
                                    session_id="s", nonce=nonce, content_key=bytes(32))
    v1_link = proto.LinkDeclaration(link_id="0123abcd", token_sha256="b" * 64, session_id="s")
    assert not auth.declarable(v2_link)
    assert auth.declarable(v1_link)


@pytest.mark.asyncio
async def test_an_unavailable_device_falls_back_to_the_shared_token_only_if_one_exists(tmp_path):
    session = _session(tmp_path, FakeControl(Issuer()),
                       keychain=FakeKeychain(relay_keychain.READ_UNAVAILABLE))
    auth = await publish_auth.resolve(session, lambda: "legacy-token")
    assert isinstance(auth, publish_auth.LegacyAuth)
    with pytest.raises(RelayAuthError):
        await publish_auth.resolve(session, lambda: None)
    (tmp_path / "ok").mkdir()
    healthy = _session(tmp_path / "ok", FakeControl(Issuer()))
    device = await publish_auth.resolve(healthy, lambda: "legacy-token")
    assert isinstance(device, publish_auth.DeviceAuth), "v2 first when it works"




class _ClosingConnection:

    def __init__(self, code: int) -> None:
        self.close_code = code
        self.sent: list = []

    async def send(self, text):
        self.sent.append(text)

    async def recv(self):
        await asyncio.Event().wait()

    async def wait_closed(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _publisher(credentials, connector, decls=None, **kw):
    async def none():
        return decls or []

    return relay_publisher.RelayPublisher(
        url="wss://r/publish", credentials=credentials, registry=_NoRegistry(),
        declarations=none, connector=connector, refresh_seconds=0.02,
        sleep=lambda s: asyncio.sleep(0), **kw)


class _NoRegistry:
    def subscribe(self, session_id):
        from src.core.bounded_stream import BoundedStream

        return BoundedStream(max_items=4, max_bytes=1024, label="t")

    def unsubscribe(self, stream, session_id):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("code,status", [(4403, "relay access revoked"),
                                         (4426, "update required")])
async def test_a_4403_or_4426_stops_retrying_and_says_why(code, status):
    dials = []

    def connector(url, dial):
        dials.append(dial)
        return _ClosingConnection(code)

    auth = publish_auth.LegacyAuth("t")

    async def credentials():
        return auth

    publisher = _publisher(credentials, connector)
    publisher.start()
    await asyncio.wait_for(publisher._task, 2)
    assert len(dials) == 1 and publisher.status == status and not publisher.connected


@pytest.mark.asyncio
async def test_a_terminal_auth_failure_stops_the_loop():
    async def credentials():
        raise RelayAuthError("revoked")

    publisher = _publisher(credentials, lambda u, d: pytest.fail("dialled"))
    publisher.start()
    await asyncio.wait_for(publisher._task, 2)
    assert publisher.status == "relay access revoked"


@pytest.mark.asyncio
async def test_v2_declares_derived_links_with_nonces_and_reauths_before_exp(tmp_path):
    issuer = Issuer()
    session = _session(tmp_path, FakeControl(issuer))
    await session.token()
    link_id, nonce = session.new_link_identity()
    good = proto.LinkDeclaration(link_id=link_id, token_sha256="a" * 64,
                                 session_id="ses_1", nonce=nonce, content_key=bytes(32),
                                 expires_at=1_900_000_000)
    keyless_id, keyless_nonce = session.new_link_identity()
    keyless = proto.LinkDeclaration(link_id=keyless_id, token_sha256="c" * 64,
                                    session_id="ses_1", nonce=keyless_nonce)
    legacy = proto.LinkDeclaration(link_id="0123abcd", token_sha256="b" * 64, session_id="ses_1")
    auth = publish_auth.DeviceAuth(session)
    auth._clock = lambda: 10 ** 10
    conn = _ClosingConnection(None)
    conn.wait_closed = lambda: asyncio.Event().wait()

    async def credentials():
        return auth

    slow = asyncio.Event()
    real_reauth = auth.reauth_frame

    async def slow_reauth():
        await slow.wait()
        return await real_reauth()

    auth.reauth_frame = slow_reauth
    publisher = _publisher(credentials, lambda u, d: conn, decls=[good, legacy, keyless])
    publisher.start()
    for _ in range(100):
        if sum('"links"' in f for f in conn.sent) >= 3:
            break
        await asyncio.sleep(0.01)
    assert sum('"links"' in f for f in conn.sent) >= 3, "a pending reauth held the passes"
    assert '"links"' in conn.sent[0], "the first frame must be links"
    slow.set()
    for _ in range(200):
        if any('"reauth"' in f for f in conn.sent):
            break
        await asyncio.sleep(0.01)
    await publisher.aclose()
    links = [json.loads(f) for f in conn.sent if '"links"' in f]
    assert links[0] == {"type": "links", "links": [
        {"link_id": link_id, "token_sha256": "a" * 64, "nonce": nonce,
         "expires_at": 1_900_000_000}]}
    reauth = next(json.loads(f) for f in conn.sent if '"reauth"' in f)
    verify_relay_token(reauth["token"], issuer.pins)
    assert publisher.protocol_version == 2


@pytest.mark.asyncio
async def test_a_fresh_install_with_no_relay_block_registers_and_publishes_on_v2(
        tmp_path, monkeypatch):
    import functools

    from src.config import auth_loader
    from src.core.db import db_path_for
    from src.core.db_migration import ensure_db_migrated

    state = tmp_path / "state"
    state.mkdir()
    config = state / "config.json"
    config.write_text("{}")
    ensure_db_migrated(state, 4, "0.0.0")
    relay_cfg = auth_loader.load(config, totp_secret="t", jwt_secret="j").relay

    for name in proto.TOKEN_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(relay_keychain, "read_publish_token", lambda: None)
    keychain, control = FakeKeychain(), FakeControl(Issuer())
    monkeypatch.setattr(relay_publisher, "DeviceSession", functools.partial(
        DeviceSession, call=control, sleep=lambda s: asyncio.sleep(0),
        key_loader=lambda install: dk.load_or_create(
            install, read=keychain.read, write=keychain.write)))
    dials: list = []
    conn = _ClosingConnection(None)
    conn.wait_closed = lambda: asyncio.Event().wait()

    def connector(url, dial):
        dials.append((url, dial))
        return conn

    monkeypatch.setattr(relay_publisher, "RelayPublisher", functools.partial(
        relay_publisher.RelayPublisher, connector=connector,
        sleep=lambda s: asyncio.sleep(0)))

    class _Store:
        async def live_relay_declarations(self):
            return []

    publisher = relay_publisher.start_if_enabled(
        relay_cfg, registry=_NoRegistry(), store=_Store(),
        db_path=db_path_for(state), version="v1.8.1")
    assert publisher is not None, "a fresh install must start the publisher"
    try:
        for _ in range(300):
            if dials:
                break
            await asyncio.sleep(0.01)
    finally:
        await publisher.aclose()
    assert [path for path, _, _ in control.calls][:2] == ["/devices", "/token"]
    url, dial = dials[0]
    assert url == "wss://relay.carnivore.ai/publish"
    assert dial.subprotocol == publish_auth.PUBLISH_SUBPROTOCOL_V2
    assert keychain.writes == 1, "the device key is minted once, in the fake"




def _bearer(sub: str = "42") -> str:
    return "h." + dk.b64url(json.dumps({"sub": sub}).encode()) + ".s"


class _Account:

    def __init__(self) -> None:
        self.token = None
        self.rotated = None
        self.signed_out = 0

    async def bearer(self, refused=None):
        if refused is not None and self.rotated is not None:
            return self.rotated
        return self.token

    async def sign_out(self):
        self.signed_out += 1
        self.token = None


class _WalledControl(FakeControl):

    def __init__(self, issuer, claim_status: int = 200, claim_409s: int = 0) -> None:
        super().__init__(issuer)
        self.claim_status = claim_status
        self.claim_409s = claim_409s
        self.revoked_bearers: set = set()
        self.allow_anon = False

    async def __call__(self, base, method, path, *, json_body=None, bearer=None):
        if path == "/devices/claim":
            self.calls.append((path, json_body, bearer))
            nonce = dk.unb64url(json_body["nonce"], 16)
            sub = account_id(bearer)
            message = rc_crypto.claim_message(json_body["device_id"], sub, json_body["ts"], nonce)
            assert rc_crypto.verify_ed25519(self.device.pub, dk.unb64url(json_body["sig"], 64), message)
            if self.claim_409s > 0:
                self.claim_409s -= 1
                return hosted_api.HostedAnswer(409, {"code": "device_owned_elsewhere"})
            if self.claim_status != 200:
                return hosted_api.HostedAnswer(self.claim_status, {"code": "device_owned_elsewhere"})
            return hosted_api.HostedAnswer(200, {"device_id": json_body["device_id"]})
        if path in ("/devices", "/token") and bearer is None and not (
                path == "/devices" and self.allow_anon):
            self.calls.append((path, json_body, bearer))
            return hosted_api.HostedAnswer(403, {"code": "account_required"})
        if path == "/token" and bearer in self.revoked_bearers:
            self.calls.append((path, json_body, bearer))
            return hosted_api.HostedAnswer(401, {"code": "session_revoked"})
        return await super().__call__(base, method, path, json_body=json_body, bearer=bearer)


def _account_session(tmp_path, control, account) -> DeviceSession:
    keychain = FakeKeychain()
    return DeviceSession(
        db_path=_db(tmp_path), version="v1.8.1", call=control, account=account,
        key_loader=lambda install: dk.load_or_create(install, read=keychain.read, write=keychain.write),
        sleep=lambda s: asyncio.sleep(0))


async def _preregistered(tmp_path, control, account) -> DeviceSession:
    session = _account_session(tmp_path, control, account)
    control.allow_anon = True
    await session.ensure_registered()
    control.allow_anon = False
    return session


@pytest.mark.asyncio
async def test_account_required_parks_the_publisher_and_a_sign_in_connects_it(tmp_path):
    account, control = _Account(), _WalledControl(Issuer())
    session = await _preregistered(tmp_path, control, account)
    dials: list = []
    conn = _ClosingConnection(None)
    conn.wait_closed = lambda: asyncio.Event().wait()

    def connector(url, dial):
        dials.append(dial)
        return conn

    async def credentials():
        return await publish_auth.resolve(session, lambda: "legacy-token")

    publisher = _publisher(credentials, connector)
    publisher.start()
    for _ in range(50):
        await asyncio.sleep(0.01)
    assert not publisher.stopped and not dials, "parked: alive, not dialled, no legacy token"
    assert publisher.status == "sign in to a carnivore account to use the relay"
    account.token = _bearer()
    publisher.on_account_change()
    assert await publisher.wait_connected(2)
    await publisher.aclose()
    assert dials[0].subprotocol == publish_auth.PUBLISH_SUBPROTOCOL_V2
    claim = next(c for c in control.calls if c[0] == "/devices/claim")
    assert claim[2] == account.token
    token_calls = [c for c in control.calls if c[0] == "/token" and c[2] is not None]
    assert token_calls and token_calls[0][2] == account.token


@pytest.mark.asyncio
async def test_a_claim_then_a_redial_uses_the_bearer_once(tmp_path):
    account, control = _Account(), _WalledControl(Issuer())
    session = await _preregistered(tmp_path, control, account)
    account.token = _bearer()
    await session.token()
    paths = [c[0] for c in control.calls]
    assert paths.index("/devices/claim") < max(i for i, p in enumerate(paths) if p == "/token")
    session.drop_token()
    await session.token()
    assert [c[0] for c in control.calls].count("/devices/claim") == 1, "bound once, recorded in meta"


@pytest.mark.asyncio
async def test_a_404_for_the_device_clears_the_bound_account_so_it_claims_again(tmp_path):
    account, control = _Account(), _WalledControl(Issuer())
    session = await _preregistered(tmp_path, control, account)
    account.token = _bearer()
    await session.token()
    assert [c[0] for c in control.calls].count("/devices/claim") == 1
    session.drop_token()
    walled, forgot = control.__call__, []

    async def forgetful(base, method, path, *, json_body=None, bearer=None):
        if path == "/token" and not forgot:
            forgot.append(1)
            return hosted_api.HostedAnswer(404, {"code": "unknown_device"})
        if path == "/devices" and forgot:
            return hosted_api.HostedAnswer(409, {"code": "device_owned_elsewhere"})
        return await walled(base, method, path, json_body=json_body, bearer=bearer)

    session._call = forgetful
    await session.token()
    assert [c[0] for c in control.calls].count("/devices/claim") == 2


@pytest.mark.asyncio
async def test_a_device_owned_by_another_account_is_terminal_with_no_reset(tmp_path):
    account, control = _Account(), _WalledControl(Issuer(), claim_status=409)
    session = await _preregistered(tmp_path, control, account)
    account.token = _bearer()
    with pytest.raises(RelayAuthError) as refused:
        await session.token()
    assert refused.value.kind == "device_owned_elsewhere" and refused.value.terminal


@pytest.mark.asyncio
async def test_a_revoked_session_rotates_once_then_parks_and_never_signs_the_account_out_if_refused_again(tmp_path):
    account, control = _Account(), _WalledControl(Issuer())
    account.token, account.rotated = _bearer(), _bearer() + "r"
    control.revoked_bearers = {account.token}
    session = _account_session(tmp_path, control, account)
    await session.token()
    assert account.signed_out == 0
    account.token = account.rotated = _bearer()
    control.revoked_bearers = {account.token}
    (tmp_path / "b").mkdir()
    fresh = _account_session(tmp_path / "b", control, account)
    with pytest.raises(RelayAuthError) as refused:
        await fresh.token()
    assert refused.value.kind == "signin_required" and account.signed_out == 0


@pytest.mark.asyncio
async def test_a_different_signed_in_account_claims_again(tmp_path):
    account, control = _Account(), _WalledControl(Issuer())
    session = await _preregistered(tmp_path, control, account)
    account.token = _bearer("42")
    await session.token()
    session.drop_token()
    account.token = _bearer("43")
    await session.token()
    claims = [c for c in control.calls if c[0] == "/devices/claim"]
    assert [c[2] for c in claims] == [_bearer("42"), _bearer("43")]


@pytest.mark.asyncio
async def test_a_lost_claim_race_is_retried_once_then_surfaced(tmp_path):
    account, control = _Account(), _WalledControl(Issuer(), claim_409s=1)
    session = await _preregistered(tmp_path, control, account)
    account.token = _bearer()
    await session.token()
    assert [c[0] for c in control.calls].count("/devices/claim") == 2
    account2, control2 = _Account(), _WalledControl(Issuer(), claim_409s=5)
    (tmp_path / "b").mkdir()
    session2 = await _preregistered(tmp_path / "b", control2, account2)
    account2.token = _bearer()
    with pytest.raises(RelayAuthError) as refused:
        await session2.token()
    assert refused.value.kind == "device_owned_elsewhere"
    assert [c[0] for c in control2.calls].count("/devices/claim") == 2
