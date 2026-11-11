
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
import structlog
from pydantic import ValidationError

from src.config import settings as app_settings
from src.core.argent import notices, pair_sync, rollout, settings as settings_module
from src.core.argent.delegate import Delegates, Minted
from src.core.argent.pair_credential import CAP_CREDENTIAL, CREDENTIAL_PATH, CredentialBody, PairRefused
from src.core.argent.pair_sync import CAP_SWITCH, SWITCH_PATH, PairSync, SwitchBody
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore

TOKEN = "FIXTURE-asicli-not-a-secret-0001"
SERVER, GATEWAY = "https://cp.argent.test", "https://gw.argent.test"
CA = "-----BEGIN CERTIFICATE-----\n" + "MIIBfakefakefakefakefakefakefakefake\n" * 3 + "-----END CERTIFICATE-----\n"
NOW = 1_800_000_000.0


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class Echoer(PairSync):

    async def export(self, only, *, bump=False, rollout_direction=None):  # type: ignore[override]
        return await super().export(only, bump=True, rollout_direction=rollout_direction)


class FixtureDelegates(Delegates):

    async def mint(self, label: str) -> Minted:
        return Minted("dlg", 3600, TOKEN)

    async def revoke_id(self, delegate_id: str) -> bool:
        return True


class Computer:
    def __init__(self, net: "Net", name: str, tmp: Path, accepts: bool, cls: type = PairSync) -> None:
        self.net, self.name, self.accepts = net, name, accepts
        self.state, self.config = tmp / name / "state", tmp / name / "config.json"
        self.state.mkdir(parents=True)
        self.config.write_text(json.dumps({"argent": {}}))
        self.keychain = Keychain()
        self.store, self.tokens = ArgentStore(self.state, clock=lambda: NOW), TokenStore(self.keychain)
        self.sync = cls(store=self.store, tokens=self.tokens, self_id=name, self_label=name.upper(), peer=lambda iid: net.link(name, iid),
                        listing=lambda: [(o, o.upper(), "connected", [CAP_SWITCH, CAP_CREDENTIAL]) for o in net.computers if o != name],
                        candidates=lambda: [o for o in net.computers if o != name], allows=lambda iid: net.computers[iid].accepts, approved=lambda _iid: True,
                        config_path=self.config, state_dir=self.state, clock=lambda: NOW)
        self.sync.credentials._delegates = FixtureDelegates(self.store, self.tokens)

    def cfg(self) -> Any:
        return settings_module.read(self.config)

    def flip(self, **block: Any) -> None:
        before = self.cfg()
        settings_module.update(lambda b: b.update(block), self.config)
        self.sync.on_settings_changed(before, self.cfg())

    def login(self, source: str = "own") -> None:
        self.store.set_login("ten_1", "id_1", "Fixture Person", 3600, source=source)
        self.tokens.write("ten_1", TOKEN)


class Net:
    def __init__(self, tmp: Path, names: Tuple[str, ...] = ("a", "b", "c", "d"), accepting: Tuple[str, ...] = ("b", "d"), cls: type = PairSync) -> None:
        self.wire: List[Tuple[str, str, str, dict]] = []
        self.computers: Dict[str, Computer] = {}
        for n in names:
            self.computers[n] = Computer(self, n, tmp, n in accepting, cls if n != "a" else PairSync)

    def link(self, sender: str, target: str):
        async def post(method: str, path: str, body: Any) -> Tuple[int, Any]:
            self.wire.append((sender, target, path, body))
            peer = self.computers[target]
            try:
                if path == SWITCH_PATH:
                    return 200, await peer.sync.receive_switch(sender, SwitchBody.model_validate(body), object())
                if not peer.accepts:
                    return 403, {}
                return 200, {"expires_at": await peer.sync.receive_credential(sender, CredentialBody.model_validate(body))}
            except ValidationError:
                return 422, {}
            except PairRefused as exc:
                return exc.status, {"code": exc.code}
        return post, [CAP_SWITCH, CAP_CREDENTIAL]

    def sent_by(self, sender: str, path: str = "") -> List[Tuple[str, str, str, dict]]:
        return [w for w in self.wire if w[0] == sender and (not path or w[2] == path)]


@pytest.fixture
def net(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Net:
    monkeypatch.setattr(app_settings, "state_dir_override", tmp_path)
    app_settings.drop_auth_config_cache()
    raised: List[str] = []
    monkeypatch.setattr(notices, "pair_login", lambda computer: raised.append(computer))
    monkeypatch.setattr(notices, "pair_login_resolved", lambda: None)
    built = Net(tmp_path)
    built.raised = raised  # type: ignore[attr-defined]
    return built


def run(net: Net, coro: Any) -> Any:
    return asyncio.run(coro)


def test_a_flip_reaches_every_listed_computer_and_never_echoes(net: Net) -> None:
    a = net.computers["a"]
    a.login()
    run(net, a.sync.credentials.push(None))
    a.flip(serverUrl=SERVER, gatewayUrl=GATEWAY, enabled=True)
    run(net, a.sync.export(None, bump=True))
    for n in "bd":
        assert (net.computers[n].cfg().enabled, net.computers[n].cfg().server_url, net.computers[n].cfg().gateway_url) == (True, SERVER, GATEWAY)
    assert (net.computers["c"].cfg().enabled, net.computers["c"].cfg().server_url) == (False, ""), "no login there: the addresses are not taken"
    assert len(net.sent_by("a", SWITCH_PATH)) == 3
    for n in "bcd":
        assert run(net, net.computers[n].sync.export(None)) == [] and net.sent_by(n) == []
    a.flip(enabled=False)
    run(net, a.sync.export(None, bump=True))
    assert [net.computers[n].cfg().enabled for n in "bcd"] == [False] * 3, "off syncs too"


def test_wrong_variant_that_echoes_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "state_dir_override", tmp_path)
    net = Net(tmp_path, cls=Echoer)
    net.computers["a"].flip(serverUrl=SERVER, gatewayUrl=GATEWAY, enabled=True)
    run(net, net.computers["a"].sync.export(None, bump=True))
    run(net, net.computers["b"].sync.export(None))
    assert net.sent_by("b"), "the guard test above would be red for this variant"


def test_an_unlisted_computer_and_an_older_clock_are_refused(net: Net) -> None:
    b = net.computers["b"]
    b.login("relay:a")
    body = SwitchBody(clock=5, enabled=True, server_url=SERVER, gateway_url=GATEWAY)
    with pytest.raises(PairRefused) as unlisted:
        run(net, b.sync.receive_switch("zz", body, object()))
    assert unlisted.value.code == "not_listed" and not b.cfg().enabled
    assert run(net, b.sync.receive_switch("a", body, object())) == {"applied": True}
    older = SwitchBody(clock=3, enabled=False, server_url=SERVER, gateway_url=GATEWAY)
    assert run(net, b.sync.receive_switch("c", older, object())) == {"applied": False} and b.cfg().enabled
    with pytest.raises(PairRefused):
        run(net, b.sync.receive_switch("a", SwitchBody(clock=9, enabled=True, server_url="ftp://x", gateway_url=""), object()))


def test_a_far_future_switch_clock_is_refused_and_never_freezes_sync(net: Net) -> None:
    b = net.computers["b"]
    b.login("relay:a")
    far = SwitchBody(clock=10 ** 18, enabled=True, server_url=SERVER, gateway_url=GATEWAY)
    assert run(net, b.sync.receive_switch("a", far, object())) == {"applied": False} and not b.cfg().enabled
    ok = SwitchBody(clock=5, enabled=True, server_url=SERVER, gateway_url=GATEWAY)
    assert run(net, b.sync.receive_switch("a", ok, object())) == {"applied": True} and b.cfg().enabled


def test_a_peer_cannot_retarget_the_addresses_of_a_computer_that_holds_a_login(net: Net) -> None:
    b = net.computers["b"]
    b.login("relay:a")
    run(net, b.sync.receive_switch("a", SwitchBody(clock=1, enabled=True, server_url=SERVER, gateway_url=GATEWAY), object()))
    b.login()
    evil = SwitchBody(clock=2, enabled=True, server_url="https://evil.test", gateway_url=GATEWAY)
    with pytest.raises(PairRefused) as refused:
        run(net, b.sync.receive_switch("c", evil, object()))
    assert refused.value.code == "address_locked" and b.cfg().server_url == SERVER
    same = SwitchBody(clock=3, enabled=False, server_url=SERVER, gateway_url=GATEWAY)
    assert run(net, b.sync.receive_switch("c", same, object())) == {"applied": True} and not b.cfg().enabled, "the switch itself still follows"


def test_the_token_goes_only_to_computers_that_accept_it_and_never_a_refresh_token(net: Net) -> None:
    a = net.computers["a"]
    a.login()
    a.flip(caPath="")
    ca_file = Path(a.state) / "ca.pem"
    ca_file.write_text(CA)
    settings_module.update(lambda b: b.update(caPath=str(ca_file)), a.config)
    with structlog.testing.capture_logs() as logs:
        pushed = run(net, a.sync.credentials.push(None))
    assert sorted(pushed) == ["b", "d"], "c has may_receive_credentials off: nothing was sent to it"
    posts = net.sent_by("a", CREDENTIAL_PATH)
    assert {p[1] for p in posts} == {"b", "d"}
    for _s, _t, _p, body in posts:
        assert set(body) == {"tenant_id", "identity_id", "display_name", "access_token", "expires_at", "ca_pem"}, "no refresh token, no other field"
        assert body["access_token"] == TOKEN
    assert net.computers["c"].keychain.items == {} and net.computers["c"].store.get_login() is None
    assert a.sync.credentials.sent["c"]["state"] == "not_accepting"
    b = net.computers["b"]
    assert b.keychain.items == {("carnivore-argent-cli", "ten_1"): TOKEN} and b.store.login_source() == "relay:a"
    assert b.cfg().ca_path.startswith(str(b.state)) and Path(b.cfg().ca_path).read_text().startswith("-----BEGIN CERTIFICATE-----")
    assert TOKEN not in json.dumps(logs, default=str), "the token never reaches a log event"
    assert json.dumps(a.sync.view(), default=str).count(TOKEN) == 0 and TOKEN not in json.dumps(b.sync.view(), default=str)


def test_wrong_variant_that_leaks_a_refresh_token_or_ignores_the_flag_is_caught(net: Net) -> None:
    body = {"tenant_id": "ten_1", "access_token": TOKEN, "expires_at": int((NOW + 3600) * 1000), "refresh_token": "r" * 30}
    with pytest.raises(ValidationError):
        CredentialBody.model_validate(body)
    with pytest.raises(ValidationError):
        CredentialBody.model_validate({**body, "refresh_token": None, "token_type": "x"})
    c = net.computers["c"]
    net.computers["a"].login()
    assert run(net, net.computers["a"].sync.credentials.push("c")) == [] and c.keychain.items == {}
    c.accepts = True
    assert run(net, net.computers["a"].sync.credentials.push("c")) == ["c"]


def test_a_copy_is_not_copied_onward_and_never_replaces_a_live_own_login(net: Net) -> None:
    a, b, d = net.computers["a"], net.computers["b"], net.computers["d"]
    a.login()
    run(net, a.sync.credentials.push("b"))
    assert run(net, b.sync.credentials.push(None)) == [] and net.sent_by("b") == [], "a copier never chains"
    d.login()
    assert run(net, a.sync.credentials.push("d")) == []
    assert d.store.login_source() == "own" and a.sync.credentials.sent["d"]["state"] == "refused"
    assert net.sent_by("a", CREDENTIAL_PATH)[-1][1] == "d"


def test_a_computer_without_a_usable_login_is_told_to_log_in_and_a_rollout_start_is_carried(net: Net, monkeypatch: pytest.MonkeyPatch) -> None:
    a = net.computers["a"]
    a.login()
    run(net, a.sync.credentials.push(None))
    monkeypatch.setattr(pair_sync.ports, "get", lambda name: object())
    begun: List[Tuple[str, str]] = []

    async def begin(direction: str) -> dict:
        begun.append(("x", direction))
        return {}

    monkeypatch.setattr(rollout, "begin", begin)
    monkeypatch.setattr(rollout, "bind", lambda state: None)
    monkeypatch.setattr(rollout, "ensure_running", lambda: True)
    a.flip(serverUrl=SERVER, gatewayUrl=GATEWAY, enabled=True)
    run(net, a.sync.export(None, bump=True, rollout_direction="on"))
    assert len(begun) == 2 and all(d == "on" for _x, d in begun), "a rollout ON starts where a login exists (b and d); c has none and is skipped"
    assert all(net.computers[n].cfg().enabled for n in "bd") and not net.computers["c"].cfg().enabled
    assert net.computers["c"].cfg().server_url == "", "c has no login: a peer never writes its addresses (the owner there configures them)"


def test_nothing_is_sent_while_nothing_changed(net: Net) -> None:
    a = net.computers["a"]
    a.flip(refuseDirectLaunch=True)
    run(net, a.sync.export(None))
    run(net, a.sync.credentials.push(None))
    assert net.wire == [] and a.store.pair_state() == (0, "")
