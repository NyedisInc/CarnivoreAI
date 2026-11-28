
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import os
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx
import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mlog_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mlog_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

from structlog.testing import capture_logs  # noqa: E402

from src.api import federation_pack_credentials_routes as cred_routes, peer_auth  # noqa: E402
from src.core.argent import device_login, notices, pair_sync, settings as argent_settings, runtime as argent_runtime  # noqa: E402
from src.core.argent.delegate import MAX_LIFE_SECONDS, Delegates  # noqa: E402
from src.core.argent.pair_credential import CredentialSender  # noqa: E402
from src.core.argent.store import ArgentStore  # noqa: E402
from src.core.argent.token_store import TokenStore  # noqa: E402
from src.core.db import connect  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.federation import mesh_grants, mesh_peers, mesh_powers, peer_client, peer_forward  # noqa: E402
from src.core.federation.mesh_client import MeshPeerClient, MeshTransport  # noqa: E402
from src.core.federation.peer_link import CONNECTED  # noqa: E402
from src.core.pack.machines import capabilities, config_state, roster_v2  # noqa: E402
from src.core.pack.machines import restrictions as restrictions_mod  # noqa: E402
from src.core.pack.machines import runtime as machines_runtime  # noqa: E402
from src.core.pack.machines.exchange import post_via  # noqa: E402
from src.core.pack.relay import consent as consent_mod  # noqa: E402
from src.core.pack.relay import login_gate, member_reach, target_side, codex_target, keychain_write, ledger_sync_store  # noqa: E402
from src.core.pack.relay import runtime as relay_runtime  # noqa: E402
from src.core.provider_ledger import poller_core, refresh_poke  # noqa: E402
from src.core.pack.relay import targets as targets_mod  # noqa: E402
from src.core.pack.relay.ddl import apply_pack_relay  # noqa: E402
from src.core.pack.relay.owner_side import Relay  # noqa: E402
from src.core.provider_ledger import keychain as keychain_mod  # noqa: E402
from tests.argent.test_argent_refresh import OWNER_TOKEN, SERVER, Argent  # noqa: E402
from tests.python.computers.test_mesh_links import A, B, C, _inputs, root  # noqa: E402,F401
from tests.python.federation.test_mesh_revocation import _changed, _linked, _serving, _world  # noqa: E402
from tests.python.pack import test_settings_signing as ss  # noqa: E402

ARGENT_CRED = "/federation/argent/credential"
ARGENT_REQ = "/federation/argent/credential/request"
CRED_PATH = "/federation/pack/credentials"
CODEX_PATH = "/federation/pack/credentials/codex"
TOKEN = "tok-" + "abcdefghij" * 4
TOKEN2 = "tok-" + "klmnopqrst" * 4
REFRESH = "refresh-" + "uvwxyzabcd" * 4


@pytest.fixture(autouse=True)
def _fresh_member_cache(monkeypatch):
    monkeypatch.setattr(member_reach, "_LAST_GOOD", None)


def _jwt(exp_s: int, extra: str = "") -> str:
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc({'exp': exp_s, 'n': extra})}.sig"


def _expiry(hours: float = 5.0):
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _claude(token: str = TOKEN, hours: float = 5.0) -> Any:
    return SimpleNamespace(access_token=token, expires_at=_expiry(hours), scopes=["user:inference"], subscription_type=None, rate_limit_tier=None)


def _codex(hours: float = 5.0) -> Any:
    when = _expiry(hours).replace(microsecond=0)
    return SimpleNamespace(access_token=_jwt(int(when.timestamp()), TOKEN), id_token=_jwt(int(when.timestamp()), "id"), account_id="acc-1",
                           expires_at=when, plan=None)


class _Env(SimpleNamespace):
    pass


def _install_fakes(monkeypatch, tmp_path) -> _Env:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    accounts = tmp_path / "auth.json"
    accounts.write_text("{}")
    monkeypatch.setattr(settings, "auth_config_file", str(accounts), raising=False)
    kc: Dict[str, str] = {}
    writes: List[str] = []

    def write_item(service, document, *, account=None, update=False, security_bin=""):
        writes.append(service)
        kc[service] = document

    monkeypatch.setattr(keychain_write, "write_item", write_item)
    monkeypatch.setattr(keychain_write, "delete_item", lambda service, **kw: kc.pop(service, None))
    monkeypatch.setattr(keychain_mod, "read_password", lambda service, **kw: kc.get(service))
    state = SimpleNamespace(restrictions=restrictions_mod.Restrictions(may_receive_credentials=True))
    real = config_state.default()

    class Cfg:

        def restrictions(self):
            return state.restrictions

        def relay_consent(self):
            return consent_mod.Consent(consent_mod.MODE_ALL)

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(config_state, "default", lambda: Cfg())
    return _Env(kc=kc, writes=writes, state=state, posts=[], bodies=[], home=home)


def _yes(p, c_yes: bool = True, b_one_way: bool = False, c_one_way: bool = False, only=("a", "b", "c")):
    out = []
    for i in _inputs(p.idents, p.ports, only):
        if i.install_id == C:
            i = dataclasses.replace(i, may_receive_logins=c_yes, one_way=c_one_way)
        if i.install_id == B:
            i = dataclasses.replace(i, one_way=b_one_way)
        out.append(i)
    return out


def _issue(p, names, inputs) -> None:
    p.alpha.refresh_roster(inputs)
    for name in names:
        p.pack[name].custody.merge_roster_v2(p.alpha.custody.roster_v2_wire(), A)


def _db_b(w) -> None:
    with closing(w.b_open()) as conn:
        apply_pack_relay(conn)
    with closing(peer_auth.open_db()) as conn:
        apply_pack_relay(conn)


def _relay(monkeypatch, p, w, env: _Env) -> Relay:
    wired = SimpleNamespace(runtime=SimpleNamespace(install_id=B, custody=p.pack["b"].custody, roster=SimpleNamespace(entries={}), label="b",
                                                    offers_reconcile=None), peers=lambda: [])
    monkeypatch.setattr(machines_runtime, "_WIRING", wired)
    monkeypatch.setattr(relay_runtime, "RELAY", None)
    monkeypatch.setattr(relay_runtime, "SYNC", None)
    monkeypatch.setattr(ledger_sync_store, "PATH", None)
    monkeypatch.setattr(poller_core, "add_snapshot_listener", lambda _fn: None)
    monkeypatch.setattr(refresh_poke, "add_credential_listener", lambda _fn: None)
    real_post_via = member_reach.post_via

    def counting(client, timeout):
        post = real_post_via(client, timeout)

        async def wrapped(method, path, body):
            env.posts.append((method, path))
            env.bodies.append((method, path, json.dumps(body, default=str)))
            return await post(method, path, body)
        return wrapped

    monkeypatch.setattr(member_reach, "post_via", counting)
    return relay_runtime.start(w.b_open, lambda: w.links_b)


async def _rehello(w) -> None:
    link, client = w.reg_b._live(C), w.reg_b.client(C)
    assert link is not None and client is not None
    await link._hello(client)


async def _setup(monkeypatch, tmp_path, root, p, w, env: _Env, **flags) -> Relay:
    monkeypatch.setattr(cred_routes, "open_db", lambda: connect(w.c_path, create=False))
    _db_b(w)
    _issue(p, ("b", "c"), _yes(p, **flags))
    await _changed(p, "c", "b")
    await _linked(p, w)
    await _rehello(w)
    return _relay(monkeypatch, p, w, env)


def _doc(env: _Env, which: str = "claude") -> Optional[dict]:
    return json.loads(next(iter(env.kc.values()))) if env.kc else None


def _walk(node: Any):
    if isinstance(node, dict):
        for k, v in node.items():
            yield str(k)
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


async def _hand(w, path: str, body: Any, token: Optional[str] = None, method: str = "POST") -> Any:
    client = w.reg_b.client(C)
    assert client is not None
    return await post_via(client, 10.0)(method, path, body)


def _good_body(profile: Optional[str] = None, token: str = TOKEN) -> dict:
    return {"account_key": "work", "profile": profile or target_side.relay_profile_name("work", B), "access_token": token,
            "expires_at": int(_expiry().timestamp() * 1000), "scopes": ["user:inference"]}


def test_a_login_lands_over_the_member_link_and_never_leaks(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)
    bodies: List[str] = []

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            relay = await _setup(monkeypatch, tmp_path, root, p, w, env)
            with capture_logs() as logs:
                assert capabilities.CAP_CREDENTIALS_MESH in w.reg_b._live(C).capabilities and member_reach.allows(C) is True
                assert await relay.push_account("work", _claude(), "claude") == [C]
                doc = _doc(env)
                assert doc["claudeAiOauth"]["accessToken"] == TOKEN and doc["carnivoreRelay"]["from"] == B
                assert not any(k.replace("_", "").replace("-", "").lower() == "refreshtoken" for k in _walk(doc))
                assert await relay.push_account("cdx", _codex(), "codex") == [C]
                files = list((env.home / ".carnivore").rglob("auth.json")) if (env.home / ".carnivore").exists() else []
                assert files and json.loads(files[0].read_text())["tokens"]["refresh_token"] == ""
                before = (dict(env.kc), len(env.writes))
                status, data = await _hand(w, CRED_PATH, {**_good_body(), "refresh_token": REFRESH})
                bodies.append(json.dumps(data))
                assert status == 422 and (dict(env.kc), len(env.writes)) == before and REFRESH not in json.dumps(data)
                service = next(iter(env.kc))
                env.kc[service] = json.dumps({"claudeAiOauth": {"accessToken": "x" * 30, "refreshToken": REFRESH}})
                held = dict(env.kc)
                status, data = await _hand(w, CRED_PATH, _good_body(token=TOKEN2))
                bodies.append(json.dumps(data))
                assert status == 409 and env.kc == held and TOKEN2 not in json.dumps(data) and REFRESH not in json.dumps(data)
                refused = await relay.push_account("work", _claude(TOKEN2, 6.0), "claude")
                assert refused == [] and env.kc == held
            text = json.dumps(logs, default=str) + "".join(bodies)
            assert TOKEN not in text and TOKEN2 not in text and REFRESH not in text
            try:
                target_side.receive(B, "work", "wrong", TOKEN, 0, scopes=[])
            except target_side.RelayRefused as exc:
                assert TOKEN not in str(exc) and TOKEN not in repr(exc)

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["c_restriction_off", "c_signed_no"])
def test_a_receiver_that_says_no_is_sent_nothing_and_stops_advertising(case, monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            relay = await _setup(monkeypatch, tmp_path, root, p, w, env, c_yes=case != "c_signed_no")
            if case == "c_restriction_off":
                assert await relay.push_account("work", _claude(), "claude") == [C]
                env.kc.clear()
                env.posts.clear()
                env.state.restrictions = restrictions_mod.Restrictions(may_receive_credentials=False)
                await _rehello(w)
            assert capabilities.CAP_CREDENTIALS_MESH not in w.reg_b._live(C).capabilities
            assert member_reach.allows(C) is False
            approved = login_gate.gate(w.b_open, caps_of=member_reach.caps_of(lambda: w.links_b))
            assert approved(C) is False
            assert await relay.push_account("work", _claude(TOKEN2, 7.0), "claude") == []
            assert env.posts == [] and env.kc == {}
            status, _ = await _hand(w, CRED_PATH, _good_body(token=TOKEN2))
            assert status in (401, 403) and env.kc == {}

    asyncio.run(scenario())


def test_one_way_computers_send_and_receive_nothing(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            relay = await _setup(monkeypatch, tmp_path, root, p, w, env)
            _issue(p, ("b", "c"), _yes(p, c_one_way=True))
            await _changed(p, "c", "b")
            assert member_reach.member_ids() == []
            assert await relay.push_account("work", _claude(), "claude") == [] and env.posts == [] and env.kc == {}
            _issue(p, ("b", "c"), _yes(p, b_one_way=True))
            await _changed(p, "c", "b")
            sess = p.links["b"]._sessions[C]
            transport = MeshTransport(sess, B, root / "b")
            try:
                client = MeshPeerClient(await transport.establish(), session=sess, self_iid=B, sign=ss.KEYS["b"].sign, trusted=lambda _p: p.links["b"]._lst)
                token = await client.bearer(force=True)
                reply = await client._send("POST", peer_client._url(CRED_PATH), token, _good_body())
                assert reply.status_code == 403 and b"computer_one_way" in reply.body and env.kc == {}
            finally:
                await transport.close()

    asyncio.run(scenario())


def test_removed_withdrawn_and_forged_approvals_send_nothing(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            relay = await _setup(monkeypatch, tmp_path, root, p, w, env)
            assert await relay.push_account("work", _claude(), "claude") == [C]
            wire_n = p.alpha.custody.roster_v2_wire()
            held = p.pack["c"].custody.held_lists()[0]
            forged = held.model_copy(update={"generation": held.generation + 5, "computers": [
                x.model_copy(update={"may_receive_logins": True}) if x.install_id == C else x for x in held.computers]})
            wire = roster_v2.to_wire_v2(forged, roster_v2.sign_v2(forged, ss.KEYS["b"], B).to_dict())
            assert p.pack["b"].custody.merge_roster_v2(wire, B) is False and p.pack["c"].custody.merge_roster_v2(wire, B) is False
            assert p.pack["b"].custody.held_lists()[0].generation == held.generation
            _issue(p, ("b", "c"), _yes(p, c_yes=False))
            await _changed(p, "c", "b")
            await _rehello(w)
            env.kc.clear()
            env.posts.clear()
            assert login_gate.gate(w.b_open, caps_of=member_reach.caps_of(lambda: w.links_b))(C) is False
            assert await relay.push_account("work", _claude(TOKEN2, 6.0), "claude") == [] and env.posts == []
            status, _ = await _hand(w, CRED_PATH, _good_body(token=TOKEN2))
            assert status in (401, 403) and env.kc == {}
            assert p.pack["b"].custody.merge_roster_v2(wire_n, A) is False and p.pack["c"].custody.merge_roster_v2(wire_n, A) is False
            _issue(p, ("b", "c"), _inputs(p.idents, p.ports, only=("a", "b")))
            await _changed(p, "c", "b")
            assert member_reach.member_ids() == []
            assert await relay.push_account("work", _claude(TOKEN2, 8.0), "claude") == [] and env.posts == []
            assert await mesh_grants.current(B) is None

    asyncio.run(scenario())


def test_a_login_never_hops_and_is_never_forwarded(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await _setup(monkeypatch, tmp_path, root, p, w, env)
            status, data = await _hand(w, CRED_PATH, _good_body(profile=target_side.relay_profile_name("work", A)))
            assert status == 422 and data["detail"]["code"] == "bad_profile" and env.kc == {}
            status, data = await _hand(w, CODEX_PATH, {"account_key": "work", "profile": codex_target.codex_relay_profile_name("work", A),
                                                       "access_token": _jwt(1), "id_token": _jwt(1), "account_id": "acc-1", "expires_at": 1})
            assert status in (422,) and env.kc == {} and not (env.home / ".carnivore").exists()
            paths = {r.path for r in peer_forward.RULES.values()} if isinstance(peer_forward.RULES, dict) else {r.path for r in peer_forward.RULES}
            assert not any("credentials" in x for x in paths)
            assert not any("credentials" in path for (_m, path), power in mesh_powers.ROUTES.items()
                           if power not in (mesh_powers.MESH_LOGINS, mesh_powers.REFUSED))
            client = w.reg_b.client(C)
            token = await client.bearer()
            sess = p.links["b"]._sessions[C]
            transport = MeshTransport(sess, B, root / "b")
            try:
                bare = MeshPeerClient(await transport.establish(), session=sess, self_iid=B, sign=ss.KEYS["b"].sign, trusted=lambda _p: None)
                reply = await bare._send("POST", peer_client._url(CRED_PATH), token, _good_body())
                assert reply.status_code != 401 and env.kc
                env.kc.clear()
                real = peer_auth._authorize_mesh

                async def untagged(claims, scope, also, conn):
                    conn.scope.pop("mesh_peer", None)
                    return await real(claims, scope, also, conn)

                monkeypatch.setattr(peer_auth, "_authorize_mesh", untagged)
                reply = await bare._send("POST", peer_client._url(CRED_PATH), token, _good_body(token=TOKEN2))
                assert reply.status_code == 401 and env.kc == {}
            finally:
                await transport.close()

    asyncio.run(scenario())


def test_with_the_switch_off_nothing_is_advertised_and_nothing_reaches_a_member(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert capabilities.CAP_CREDENTIALS_MESH not in capabilities.names() and member_reach.member_ids() == []
    star = SimpleNamespace(client=lambda iid: "client-" + iid if iid == "star" else None, capabilities=lambda iid: ["pack.credentials"])
    peer = member_reach.lookup(lambda: star)
    assert peer("star") is not None and peer("star")[1] == ["pack.credentials"] and peer("member") is None
    assert peer(C) is None and member_reach.allows("member") is None
    assert member_reach.gate_caps_of(lambda: star)("star") == member_reach.caps_of(lambda: star)("star") and member_reach.gate_caps_of(lambda: star)(C) == member_reach.caps_of(lambda: star)(C)
    assert member_reach.via_member(lambda: star)(C) is False and member_reach.via_member(lambda: star)("star") is False
    assert mesh_powers.power_for("POST", "/api/v1/federation/argent/credential") == mesh_powers.MESH_LOGINS
    with pytest.raises(Exception) as refused:
        asyncio.run(peer_auth._authorize_mesh({}, "credentials", (), SimpleNamespace(scope={"mesh_peer": "x"})))
    assert getattr(refused.value, "status_code", None) == 401
    asyncio.run(member_reach.dial_due(lambda: None, lambda: star, "work", "claude", 1))
    assert mesh_grants.derive(None, self_iid=C, peer_iid=B, cert_sha="x", restrictions=restrictions_mod.Restrictions(), has_replica=False) is None
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert capabilities.CAP_CREDENTIALS_MESH in capabilities.names()


def _state(w, account: str = "work") -> Optional[str]:
    with closing(w.b_open()) as conn:
        rows = [r.state for r in targets_mod.list_all(conn) if r.account_key == account and r.target_install_id == C]
    return rows[0] if rows else None


def test_a_member_401_is_retried_and_a_restriction_403_stays_refused(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            relay = await _setup(monkeypatch, tmp_path, root, p, w, env)
            real = peer_auth._authorize_mesh

            async def untagged(claims, scope, also, conn):
                conn.scope.pop("mesh_peer", None)
                return await real(claims, scope, also, conn)

            monkeypatch.setattr(peer_auth, "_authorize_mesh", untagged)
            assert await relay.push_account("work", _claude(), "claude") == [] and env.kc == {}
            assert env.posts and _state(w) == "failed"
            monkeypatch.setattr(peer_auth, "_authorize_mesh", real)
            relay._retry_at.clear()
            assert await relay.push_account("work", _claude(TOKEN2, 6.0), "claude") == [C] and _state(w) == "pushed"
            env.state.restrictions = restrictions_mod.Restrictions(may_receive_credentials=False)
            relay._retry_at.clear()
            assert await relay.push_account("work", _claude(TOKEN, 7.0), "claude") == [] and _state(w) == "refused"

    asyncio.run(scenario())


def test_dials_run_beside_the_pushes(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            relay = await _setup(monkeypatch, tmp_path, root, p, w, env)
            release = asyncio.Event()
            reached: List[str] = []

            async def slow_reach(account_key: str, provider: str, expiry_ms: int) -> None:
                reached.append(account_key)
                await release.wait()

            relay._reach = slow_reach
            task = asyncio.get_running_loop().create_task(relay.push_account("work", _claude(), "claude"))
            for _ in range(500):
                if ("POST", CRED_PATH) in env.posts:
                    break
                await asyncio.sleep(0.01)
            assert ("POST", CRED_PATH) in env.posts and not release.is_set() and not task.done() and reached == ["work"]
            release.set()
            assert await asyncio.wait_for(task, 5.0) == [C]

    asyncio.run(scenario())


def test_dial_due_with_the_switch_on(monkeypatch, tmp_path):
    ids = [f"iid-{n}" for n in range(9)]
    clock = [1000.0]
    path = tmp_path / "b.db"

    def open_db():
        return connect(path)

    with closing(open_db()) as conn:
        apply_pack_relay(conn)
        targets_mod.arm_default(conn, "work", ids, "iid-self", "claude")
        targets_mod.record(conn, "work", ids[0], "refused", 5_000)
        targets_mod.record(conn, "work", ids[1], "pushed", 5_000)
    connects: List[str] = []

    async def connect_rec(_links, iid):
        connects.append(iid)

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh_peers, "REGISTRY", SimpleNamespace())
    monkeypatch.setattr(mesh_peers, "connect", connect_rec)
    monkeypatch.setattr(member_reach, "member_ids", lambda: list(ids))
    monkeypatch.setattr(member_reach, "_member_caps", lambda _iid: None)
    monkeypatch.setattr(member_reach, "_dialed", {})
    monkeypatch.setattr(member_reach, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(login_gate, "gate", lambda _open_db, caps_of: (lambda _iid: True))
    links = SimpleNamespace(client=lambda _iid: None)
    accepts = lambda iid, account: iid != ids[2]  # noqa: E731

    async def scenario() -> None:
        dial = lambda: member_reach.dial_due(open_db, lambda: links, "work", "claude", 5_000, accepts=accepts)  # noqa: E731
        await dial()
        assert connects == ids[3:7] and len(connects) == member_reach.MAX_DIALS_PER_PASS
        await dial()
        assert connects == ids[3:9]
        await dial()
        assert connects == ids[3:9]
        clock[0] += member_reach.DIAL_BACKOFF_SECONDS + 1
        await dial()
        assert connects[6:] == ids[3:7]
        def boom(*_a, **_k):
            raise RuntimeError("secret-looking text")

        monkeypatch.setattr(member_reach, "_due", boom)
        with capture_logs() as logs:
            assert await dial() is None
        failed = [e for e in logs if e["event"] == "pack_relay_dial_failed"]
        assert failed and failed[0]["error_type"] == "RuntimeError" and "secret-looking" not in json.dumps(logs, default=str)

    asyncio.run(scenario())


def test_an_unexpected_error_in_a_relay_pass_is_logged_and_clears_busy(monkeypatch, tmp_path):
    relay = Relay(open_db=lambda: connect(tmp_path / "x.db"), peer=lambda _iid: None, notify=lambda: None, self_id=B)

    async def broken(*_a, **_k):
        raise KeyError("work")

    monkeypatch.setattr(relay, "push_account", broken)
    relay._busy.add("work")

    async def scenario() -> None:
        with capture_logs() as logs:
            await relay._run("work", object())
        assert [e["error"] for e in logs if e["event"] == "pack_relay_pass_failed"] == ["KeyError"] and relay._busy == set()

    asyncio.run(scenario())




class _Keychain:

    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


def _own_login(store: ArgentStore, tokens: TokenStore, token: str = OWNER_TOKEN, source: str = "own") -> None:
    tokens.write("ten_1", token)
    store.set_login("ten_1", "idn_1", "Owner", 7 * 86400, source=source)


def _argent_rig(monkeypatch, tmp_path, w, relay_source: str = "own") -> SimpleNamespace:
    monkeypatch.setattr(argent_settings, "add_listener", lambda _fn: None)
    monkeypatch.setattr(device_login, "poke_after_login", lambda: None)
    monkeypatch.setattr(notices, "pair_login_resolved", lambda: None)
    monkeypatch.setattr(settings, "state_dir_override", tmp_path / "state", raising=False)
    (tmp_path / "b_argent").mkdir()
    b_store, b_kc = ArgentStore(tmp_path / "b_argent"), _Keychain()
    b_tokens = TokenStore(b_kc)
    _own_login(b_store, b_tokens, source=relay_source)
    monkeypatch.setattr(argent_runtime, "get_runtime", lambda: SimpleNamespace(store=b_store, tokens=b_tokens))
    monkeypatch.setattr(pair_sync, "PAIR", None)
    b_sync = pair_sync.start(lambda: w.links_b)
    argent, flags = Argent(), SimpleNamespace(mint_status=None, mint_life=86400)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/my/cli/delegate":
            if flags.mint_status:
                return httpx.Response(flags.mint_status, json={"error": {"code": "x"}})
            reply = await argent.handle(request)
            if flags.mint_life != 86400 and reply.status_code == 201:
                return httpx.Response(201, json={**json.loads(reply.content), "expires_in": flags.mint_life})
            return reply
        return await argent.handle(request)

    cfg = SimpleNamespace(server_url=SERVER, ca_path="")
    b_sync.credentials._delegates = Delegates(b_store, b_tokens, read_settings=lambda: cfg, transport=httpx.MockTransport(handler))
    b_sync.credentials._read_settings = lambda: cfg
    c_dir = tmp_path / "c_argent"
    c_dir.mkdir()
    (c_dir / "config.json").write_text(json.dumps({"argent": {}}))
    c_store, c_kc = ArgentStore(c_dir), _Keychain()
    c_sync = pair_sync.PairSync(store=c_store, tokens=TokenStore(c_kc), self_id=C, self_label="c", peer=lambda _iid: None, listing=lambda: [],
                                candidates=lambda: [], allows=lambda _iid: True, config_path=c_dir / "config.json", state_dir=c_dir, members=lambda: [B])
    monkeypatch.setattr(pair_sync, "PAIR", c_sync)
    return SimpleNamespace(b=b_sync, c=c_sync, argent=argent, flags=flags, b_store=b_store, c_store=c_store, c_kc=c_kc, b_kc=b_kc, cfg=cfg)


def _argent_posts(env: _Env) -> List[Any]:
    return [x for x in env.bodies if x[1] == ARGENT_CRED]


def test_an_argent_delegate_lands_over_the_member_link_bound_to_its_computer(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await _setup(monkeypatch, tmp_path, root, p, w, env)
            rig = _argent_rig(monkeypatch, tmp_path, w)
            with capture_logs() as logs:
                await rig.b.credentials_pass()
            assert rig.c_store.login_source() == "relay:" + B and list(rig.c_kc.items.values()) == ["DELEGATE-token-fixture-000001"]
            mints = [c for c in rig.argent.calls if c[1] == "/v1/my/cli/delegate"]
            assert len(mints) == 1 and mints[0][2] == OWNER_TOKEN
            record = rig.b_store.delegate_get(C)
            assert record["id"] == "dlg-1" and "DELEGATE-token" not in json.dumps(record)
            posts = _argent_posts(env)
            assert len(posts) == 1
            wire = json.loads(posts[0][2])
            assert set(wire) == {"tenant_id", "identity_id", "display_name", "access_token", "expires_at", "ca_pem"}
            assert wire["expires_at"] <= (time.time() + 86400 + 5) * 1000 and wire["access_token"] != OWNER_TOKEN
            assert OWNER_TOKEN not in json.dumps(env.bodies) + json.dumps(logs, default=str)
            before = dict(rig.c_kc.items)
            status, data = await _hand(w, ARGENT_CRED, {**wire, "refresh_token": REFRESH})
            assert status == 422 and data["detail"]["code"] == "bad_pair_body" and rig.c_kc.items == before and REFRESH not in json.dumps(data)
            (tmp_path / "bind").mkdir()
            store2, kc2 = ArgentStore(tmp_path / "bind"), _Keychain()
            tokens2, argent2, sent = TokenStore(kc2), Argent(), {}
            _own_login(store2, tokens2)

            def peer(iid: str):
                async def post(_method, _path, body):
                    sent[iid] = body
                    return 200, {"ok": True}
                return post, ["argent.pair.credential"]

            sender = CredentialSender(store=store2, tokens=tokens2, peer=peer, candidates=lambda: ["m-x", "m-y"], allows=lambda _iid: True, approved=lambda _iid: True,
                                      read_settings=lambda: rig.cfg, delegates=Delegates(store2, tokens2, read_settings=lambda: rig.cfg, transport=httpx.MockTransport(argent2.handle)),
                                      label=lambda iid: "label-" + iid)
            assert sorted(await sender.push()) == ["m-x", "m-y"]
            for iid in ("m-x", "m-y"):
                assert argent2.live[store2.delegate_get(iid)["id"]] == sent[iid]["access_token"]
            assert sent["m-x"]["access_token"] != sent["m-y"]["access_token"]

    asyncio.run(scenario())


def test_nothing_argent_is_sent_without_a_live_delegate_route_or_a_short_life_and_a_copy_is_never_forwarded(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await _setup(monkeypatch, tmp_path, root, p, w, env)
            rig = _argent_rig(monkeypatch, tmp_path, w)
            assert rig.b.credentials._max_life == MAX_LIFE_SECONDS
            errors: List[str] = []
            with capture_logs() as logs:
                rig.argent.delegate_route = False
                await rig.b.credentials_pass()
                assert _argent_posts(env) == [] and rig.b.credentials.sent[C]["state"] == "no_delegate"
                rig.argent.delegate_route = True
                for status, state in ((500, "failed"), (401, "failed")):
                    rig.b.credentials._retry_at.clear()
                    rig.flags.mint_status = status
                    try:
                        await rig.b.credentials_pass()
                    except Exception as exc:  # noqa: BLE001
                        errors.append(str(exc) + repr(exc))
                    assert _argent_posts(env) == [] and rig.b.credentials.sent[C]["state"] == state
                rig.flags.mint_status = None
                rig.flags.mint_life = 90000
                rig.b.credentials._retry_at.clear()
                await rig.b.credentials_pass()
                assert _argent_posts(env) == [] and rig.b.credentials.sent[C]["state"] == "too_long"
                assert rig.argent.live == {} and ("DELETE" in [c[0] for c in rig.argent.calls])
            text = json.dumps(env.bodies) + json.dumps(logs, default=str) + "".join(errors)
            assert OWNER_TOKEN not in text and "DELEGATE-token" not in text
            assert rig.c_kc.items == {} and rig.c_store.get_login() is None
            rig.b_store.set_login("ten_1", "idn_1", "Owner", 7 * 86400, source="relay:" + A)
            rig.flags.mint_life = 86400
            rig.b.credentials._retry_at.clear()
            minted = rig.argent.count("/v1/my/cli/delegate")
            await rig.b.credentials_pass()
            assert rig.argent.count("/v1/my/cli/delegate") == minted and _argent_posts(env) == []

    asyncio.run(scenario())


def test_an_argent_request_is_bound_to_the_authenticated_sender(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await _setup(monkeypatch, tmp_path, root, p, w, env)
            rig = _argent_rig(monkeypatch, tmp_path, w)
            _own_login(rig.c_store, TokenStore(rig.c_kc), "OWNERC-asicli-fixture-token-000009")
            calls: List[Any] = []

            async def push(only=None, force=False):
                calls.append((only, force))
                return []

            monkeypatch.setattr(rig.c.credentials, "push", push)
            status, _ = await _hand(w, ARGENT_REQ, {"install_id": "iid-x"})
            assert status == 200 and calls == [(B, True)]
            calls.clear()
            rig.c._members = lambda: []
            status, _ = await _hand(w, ARGENT_REQ, {})
            assert status == 200 and calls == []
            rig.c._members = lambda: [B]
            _issue(p, ("b", "c"), _yes(p, b_one_way=True))
            await _changed(p, "c", "b")
            sess = p.links["b"]._sessions[C]
            transport = MeshTransport(sess, B, root / "b")
            try:
                client = MeshPeerClient(await transport.establish(), session=sess, self_iid=B, sign=ss.KEYS["b"].sign, trusted=lambda _p: p.links["b"]._lst)
                token = await client.bearer(force=True)
                reply = await client._send("POST", peer_client._url(ARGENT_REQ), token, {})
                assert reply.status_code == 403 and b"computer_one_way" in reply.body and calls == []
            finally:
                await transport.close()

    asyncio.run(scenario())


def test_a_withdrawn_or_ended_yes_revokes_the_delegate_and_a_dropped_link_does_not(monkeypatch, tmp_path, root):
    w = _world(monkeypatch, tmp_path, root)
    env = _install_fakes(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with _serving(monkeypatch, tmp_path, root, w, attach=("c",)) as p:
            await _setup(monkeypatch, tmp_path, root, p, w, env)
            rig = _argent_rig(monkeypatch, tmp_path, w)
            await rig.b.credentials_pass()
            assert list(rig.argent.live) == ["dlg-1"] and len(_argent_posts(env)) == 1
            wire_n = p.alpha.custody.roster_v2_wire()
            real_link = member_reach._member_caps
            monkeypatch.setattr(member_reach, "_member_caps", lambda _iid: None)
            assert member_reach.caps_of(lambda: w.links_b)(C) == [] and member_reach.gate_caps_of(lambda: w.links_b)(C) == [capabilities.CAP_CREDENTIALS_MESH]
            await rig.b.credentials_pass()
            assert list(rig.argent.live) == ["dlg-1"] and len(_argent_posts(env)) == 1
            monkeypatch.setattr(member_reach, "_member_caps", real_link)
            _issue(p, ("b", "c"), _yes(p, c_yes=False))
            await _changed(p, "c", "b")
            await _rehello(w)
            await rig.b.credentials_pass()
            assert rig.argent.live == {} and rig.b_store.delegate_get(C) is None and len(_argent_posts(env)) == 1
            assert p.pack["b"].custody.merge_roster_v2(wire_n, A) is False and p.pack["c"].custody.merge_roster_v2(wire_n, A) is False
            status, _ = await _hand(w, ARGENT_CRED, json.loads(_argent_posts(env)[0][2]))
            assert status in (401, 403)
            _issue(p, ("b", "c"), _yes(p))
            await _changed(p, "c", "b")
            await _rehello(w)
            await rig.b.credentials_pass()
            assert len(rig.argent.live) == 1 and len(_argent_posts(env)) == 2
            env.state.restrictions = restrictions_mod.Restrictions(may_receive_credentials=False)
            await _rehello(w)
            await rig.b.credentials_pass()
            assert rig.argent.live == {} and rig.b_store.delegate_get(C) is None and len(_argent_posts(env)) == 2
            env.state.restrictions = restrictions_mod.Restrictions(may_receive_credentials=True)
            await _rehello(w)
            rig.b.credentials._retry_at.clear()
            await rig.b.credentials_pass()
            assert len(rig.argent.live) == 1 and len(_argent_posts(env)) == 3
            _issue(p, ("b", "c"), _inputs(p.idents, p.ports, only=("a", "b")))
            await _changed(p, "c", "b")
            await rig.b.credentials_pass()
            assert rig.argent.live == {} and rig.b_store.delegate_get(C) is None and len(_argent_posts(env)) == 3

    asyncio.run(scenario())
