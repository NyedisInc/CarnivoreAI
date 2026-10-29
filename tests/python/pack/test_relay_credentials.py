
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import stat
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from pydantic import ValidationError

from src.api.federation_pack_credentials_routes import CredentialBody
from src.core.pack.relay import consent as consent_mod, offers as offers_mod, owner_side, target_side, targets
from src.core.pack.relay.ddl import apply_pack_relay
from src.core.provider_ledger.credentials import claude_keychain_services

FAKE_TOKEN = "fake-access-token-" + "A1b2C3d4E5f6G7h8" * 3
FAKE_SECURITY = textwrap.dedent('''\
    import json, os, sys
    root = os.environ["FAKE_SECURITY_DIR"]
    argv = sys.argv[1:]
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    with open(os.path.join(root, "calls.jsonl"), "a") as log:
        log.write(json.dumps({"argv": argv, "stdin": stdin}) + "\\n")
    def opt(words, flag):
        return words[words.index(flag) + 1] if flag in words else None
    def path(service):
        return os.path.join(root, "items", service.replace("/", "_"))
    if argv[:1] == ["-i"]:
        for line in stdin.splitlines():
            words = line.split(None, 1)
            if not words or words[0] != "add-generic-password":
                continue
            import shlex
            parts = shlex.split(line)
            os.makedirs(os.path.join(root, "items"), exist_ok=True)
            if os.path.exists(path(opt(parts, "-s"))) and "-U" not in parts:
                continue  # the real tool refuses to add over an existing item (and -i still exits 0)
            open(path(opt(parts, "-s")), "w").write(bytes.fromhex(opt(parts, "-X")).decode())
        for line in stdin.splitlines():
            if line.startswith("delete-generic-password"):
                import shlex
                parts = shlex.split(line)
                if os.path.exists(path(opt(parts, "-s"))):
                    os.remove(path(opt(parts, "-s")))
        sys.exit(0)
    if argv[:1] == ["find-generic-password"] and "-w" in argv:
        if os.path.exists(os.path.join(root, "unreadable")):
            sys.exit(51)  # an item that exists but cannot be read (locked, or its ACL refuses us)
        try:
            sys.stdout.write(open(path(opt(argv, "-s"))).read() + "\\n")
        except FileNotFoundError:
            sys.exit(44)
        sys.exit(0)
    sys.exit(1)
''')


@pytest.fixture()
def fake_security(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tuple[Path, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "security.py").write_text(FAKE_SECURITY)
    exe = bindir / "security"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bindir}/security.py" "$@"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    root = tmp_path / "fake-store"
    root.mkdir()
    monkeypatch.setenv("FAKE_SECURITY_DIR", str(root))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return root, str(exe)


def _calls(root: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]


@dataclass
class FakeCredential:
    access_token: str
    expires_at: datetime
    scopes: Tuple[str, ...] = ("user:inference", "user:profile")
    subscription_type: Optional[str] = "max"
    rate_limit_tier: Optional[str] = None
    refresh_token: str = field(default="fake-refresh-token-must-never-leave", repr=False)


def _expiry_ms(hours: float = 8) -> Tuple[datetime, int]:
    when = datetime.now(timezone.utc) + timedelta(hours=hours)
    return when, int(when.timestamp() * 1000)


SENDER = "install-a"


def _name(key: str = "acme", sender: str = SENDER) -> str:
    return target_side.relay_profile_name(key, sender)


def _service(home: Path, key: str = "acme", sender: str = SENDER) -> str:
    return claude_keychain_services(target_side.relay_profile_dir(key, sender, home))[0]


def _receive(exe: str, home: Path, expiry_ms: int, *, key: str = "acme", sender: str = SENDER, **extra: Any) -> int:
    return target_side.receive(sender, key, _name(key, sender), FAKE_TOKEN, expiry_ms,
                               scopes=extra.pop("scopes", ["user:inference"]), home=home, security_bin=exe, **extra)


def test_access_only_credential_goes_through_stdin(fake_security, tmp_path):
    root, exe = fake_security
    _, expiry_ms = _expiry_ms()
    home = tmp_path / "home"

    _receive(exe, home, expiry_ms, subscription_type="max")

    calls = _calls(root)
    write = next(c for c in calls if c["argv"][:1] == ["-i"])
    assert write["argv"] == ["-i"], "the secret must travel on stdin, argv is just -i"
    for call in calls:
        assert FAKE_TOKEN not in " ".join(call["argv"])
    assert write["stdin"].startswith("add-generic-password -s "), "a fresh item is added WITHOUT -U"
    service = _service(home)
    stored = json.loads((root / "items" / service).read_text())
    oauth = stored["claudeAiOauth"]
    assert oauth["accessToken"] == FAKE_TOKEN and oauth["expiresAt"] == expiry_ms
    assert "refreshToken" not in oauth and "refresh" not in json.dumps(stored).lower()
    assert stored["carnivoreRelay"] == {"from": SENDER}
    assert (home / ".carnivore" / "accounts" / _name()).is_dir()


def test_relay_refuses_an_account_whose_setting_is_off_and_never_sends_a_refresh_token(fake_security, tmp_path):
    root, exe = fake_security
    db = tmp_path / "relay.db"

    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db))
        conn.isolation_level = None
        return conn

    with open_db() as conn:
        apply_pack_relay(conn)

    sent: List[Dict[str, Any]] = []

    async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        sent.append(body or {})
        target_side.receive("iid-owner", body["account_key"], body["profile"], body["access_token"], body["expires_at"],
                            scopes=body["scopes"], subscription_type=body["subscription_type"],
                            home=tmp_path / "peer-home", security_bin=exe)
        return 200, {"ok": True}

    relay = owner_side.Relay(open_db=open_db, peer=lambda iid: (post, [owner_side.CAP_CREDENTIALS]), notify=lambda: None,
                        self_id="iid-owner")
    when, expiry_ms = _expiry_ms()
    credential = FakeCredential(FAKE_TOKEN, when)

    assert asyncio.run(relay.push_account("acme", credential)) == []
    assert sent == [] and not (root / "calls.jsonl").exists()

    with open_db() as conn:
        targets.set_machines(conn, "acme", ["peer-b"], "iid-owner")
    assert asyncio.run(relay.push_account("acme", credential)) == ["peer-b"]
    assert len(sent) == 1
    assert set(sent[0]) == {"account_key", "profile", "access_token", "expires_at", "scopes", "subscription_type",
                            "rate_limit_tier"}
    assert credential.refresh_token not in json.dumps(sent[0])
    with open_db() as conn:
        row = targets.list_all(conn)[0]
    assert (row.state, row.last_expiry_pushed) == ("pushed", expiry_ms)

    assert asyncio.run(relay.push_account("acme", credential)) == []
    with open_db() as conn:
        assert targets.set_machines(conn, "acme", [], "iid-owner") == ["peer-b"]
    later = FakeCredential(FAKE_TOKEN, when + timedelta(hours=8))
    assert asyncio.run(relay.push_account("acme", later)) == [] and len(sent) == 1

    with pytest.raises(ValidationError):
        CredentialBody.model_validate({**sent[0], "refresh_token": "x"})
    with pytest.raises(ValidationError):
        CredentialBody.model_validate({**sent[0], "refreshToken": "x"})


def test_a_rotated_access_token_with_a_newer_expiry_is_pushed_again_and_an_older_one_is_not(tmp_path):
    db = tmp_path / "relay.db"

    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db))
        conn.isolation_level = None
        return conn

    with open_db() as conn:
        apply_pack_relay(conn)
        targets.set_machines(conn, "acme", ["peer-b"], "iid-owner")
    sent: List[Dict[str, Any]] = []

    async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        sent.append(body or {})
        return 200, {"ok": True}

    relay = owner_side.Relay(open_db=open_db, peer=lambda iid: (post, [owner_side.CAP_CREDENTIALS]), notify=lambda: None,
                             self_id="iid-owner")
    when, first_ms = _expiry_ms()
    assert asyncio.run(relay.push_account("acme", FakeCredential(FAKE_TOKEN, when))) == ["peer-b"]

    rotated = FakeCredential(FAKE_TOKEN + "-rotated", when + timedelta(hours=8))
    assert asyncio.run(relay.push_account("acme", rotated)) == ["peer-b"]
    assert [b["expires_at"] for b in sent] == [first_ms, first_ms + 8 * 3600 * 1000]
    assert sent[1]["access_token"] == rotated.access_token and rotated.refresh_token not in json.dumps(sent)
    with open_db() as conn:
        assert targets.list_all(conn)[0].last_expiry_pushed == first_ms + 8 * 3600 * 1000

    assert asyncio.run(relay.push_account("acme", rotated)) == []
    assert asyncio.run(relay.push_account("acme", FakeCredential(FAKE_TOKEN, when))) == [] and len(sent) == 2



def _seed(root: Path, service: str, document: Dict[str, Any]) -> str:
    (root / "items").mkdir(exist_ok=True)
    (root / "items" / service).write_text(json.dumps(document))
    return json.dumps(document)


def test_push_onto_an_item_with_a_refresh_token_is_refused_and_untouched(fake_security, tmp_path):
    root, exe = fake_security
    _, expiry_ms = _expiry_ms()
    home = tmp_path / "home"
    service = _service(home)
    before = _seed(root, service, {"claudeAiOauth": {"accessToken": "old", "refreshToken": "fake-refresh-value"}})
    with pytest.raises(target_side.RelayRefused) as caught:
        _receive(exe, home, expiry_ms)
    assert (caught.value.code, caught.value.status) == ("relay_profile_conflict", 409)
    assert (root / "items" / service).read_text() == before
    _seed(root, service, {"claudeAiOauth": {"accessToken": "old"}})
    with pytest.raises(target_side.RelayRefused):
        _receive(exe, home, expiry_ms)
    (root / "items" / service).write_text("not json")
    with pytest.raises(target_side.RelayRefused):
        _receive(exe, home, expiry_ms)
    for extra in ({"reserved_names": {_name()}}, {"reserved_services": {service}}):
        (root / "items" / service).unlink(missing_ok=True)
        with pytest.raises(target_side.RelayRefused) as caught:
            _receive(exe, home, expiry_ms, **extra)
        assert caught.value.status == 409 and not (root / "items" / service).exists()


def test_relay_profile_is_bound_to_the_sending_peer(fake_security, tmp_path):
    root, exe = fake_security
    _, expiry_ms = _expiry_ms()
    home = tmp_path / "home"
    _receive(exe, home, expiry_ms, sender="install-a")
    first = (root / "items" / _service(home, sender="install-a")).read_text()
    _receive(exe, home, expiry_ms, sender="install-b")
    assert _service(home, sender="install-a") != _service(home, sender="install-b")
    assert (root / "items" / _service(home, sender="install-a")).read_text() == first
    with pytest.raises(target_side.RelayRefused) as caught:
        target_side.receive("install-b", "acme", _name(sender="install-a"), FAKE_TOKEN, expiry_ms, scopes=[],
                            home=home, security_bin=exe)
    assert caught.value.code == "bad_profile"
    service_b = _service(home, sender="install-b")
    other = _seed(root, service_b, {"claudeAiOauth": {"accessToken": "x"}, "carnivoreRelay": {"from": "install-a"}})
    with pytest.raises(target_side.RelayRefused) as caught:
        _receive(exe, home, expiry_ms, sender="install-b")
    assert (caught.value.code, caught.value.status) == ("relay_peer_conflict", 409)
    assert (root / "items" / service_b).read_text() == other
    _receive(exe, home, expiry_ms + 1000, sender="install-a")
    assert target_side.revoke("install-b", "acme", home=home, security_bin=exe) is False
    assert (root / "items" / service_b).exists()
    assert target_side.revoke("install-a", "acme", home=home, security_bin=exe) is True
    assert not (root / "items" / _service(home, sender="install-a")).exists()


def test_bounds_refuse_oversized_values(fake_security, tmp_path):
    root, exe = fake_security
    home = tmp_path / "home"
    _, expiry_ms = _expiry_ms()
    for bad in ({"scopes": ["x" * 65]}, {"scopes": ["has space"]}, {"scopes": ["a" * 60] * 40}):
        with pytest.raises(target_side.RelayRefused) as caught:
            _receive(exe, home, expiry_ms, **bad)
        assert caught.value.status == 422
    for far in (_expiry_ms(hours=30)[1], 10 ** 40):
        with pytest.raises(target_side.RelayRefused) as caught:
            _receive(exe, home, far)
        assert caught.value.code == "expired"
    assert not (root / "calls.jsonl").exists()


def test_receiving_credentials_defaults_off():
    from src.core.pack.machines import restrictions

    for raw in (None, {}, {"may_host_agents": True}):
        r = restrictions.from_dict(raw)
        assert r.may_receive_credentials is False
        assert "credentials" not in restrictions.scopes_for(r, tracks_master=True)
        assert restrictions.check(r, restrictions.ACTION_RECEIVE_CREDENTIALS) == "may_receive_credentials"
    on = restrictions.Restrictions(may_receive_credentials=True)
    assert "credentials" in restrictions.scopes_for(on, tracks_master=True)
    assert restrictions.loosened_rules(restrictions.Restrictions(), on) == ["may_receive_credentials"]


def test_mcp_cannot_enable_the_relay_or_receiving():
    from types import SimpleNamespace

    from src.core.mcp import pack_machines_tools, pack_relay_tools
    from src.core.mcp.common import ToolError

    routed: List[Any] = []

    def route(*args: Any) -> Dict[str, Any]:
        routed.append(args)
        return {}

    for fn, args in ((pack_relay_tools._set, {"account": "work", "machines": ["hosta"]}),
                     (pack_machines_tools._restrictions_set, {"machine": "self", "may_receive_credentials": True})):
        with pytest.raises(ToolError):
            fn(SimpleNamespace(route=route, request=None, args=args))
    assert routed == []
    pack_relay_tools._set(SimpleNamespace(route=route, request=None, args={"account": "work", "machines": []}))
    pack_machines_tools._restrictions_set(SimpleNamespace(route=route, request=None,
                                                          args={"machine": "self", "may_receive_credentials": False}))
    assert len(routed) == 2


def test_refusal_is_sticky_and_a_refusing_target_is_not_sent_the_token(tmp_path):
    db = tmp_path / "relay.db"

    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db))
        conn.isolation_level = None
        return conn

    with open_db() as conn:
        apply_pack_relay(conn)
        targets.set_machines(conn, "work", ["peer-b"], "iid-owner")
    sent: List[Any] = []
    verdict = {"allows": False, "status": 401}

    async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        sent.append((method, path))
        return verdict["status"], {}

    now = [1000.0]
    relay = owner_side.Relay(open_db=open_db, peer=lambda iid: (post, [owner_side.CAP_CREDENTIALS]), notify=lambda: None,
                             self_id="iid-owner", allows=lambda iid: verdict["allows"], clock=lambda: now[0])
    cred = FakeCredential(FAKE_TOKEN, _expiry_ms()[0])
    assert asyncio.run(relay.push_account("work", cred)) == [] and sent == []
    verdict["allows"] = True
    now[0] += 100
    assert asyncio.run(relay.push_account("work", cred)) == [] and len(sent) == 1
    now[0] += 1000
    assert asyncio.run(relay.push_account("work", cred)) == [] and len(sent) == 1
    with open_db() as conn:
        assert targets.list_all(conn)[0].state == "refused"
        targets.set_machines(conn, "work", ["peer-b"], "iid-owner")
        assert targets.list_all(conn)[0].state == "on"


@pytest.fixture()
def receive_app(fake_security, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import federation_pack_credentials_routes as routes
    from src.api.auth import require_auth
    from src.api.peer_auth import OWNER, Principal
    from src.core.pack.machines import config_state, restrictions

    root, exe = fake_security
    monkeypatch.setattr(target_side.keychain_write, "SECURITY_BIN", exe)
    monkeypatch.setattr(target_side.receive, "__kwdefaults__", {**target_side.receive.__kwdefaults__, "security_bin": exe})
    monkeypatch.setattr(target_side.revoke, "__kwdefaults__", {**target_side.revoke.__kwdefaults__, "security_bin": exe})
    monkeypatch.setattr(target_side.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(routes, "_local_reservations", lambda: (set(), set()))
    owner_of: set = set()
    monkeypatch.setattr(routes, "_is_owner_of", lambda key: key in owner_of)
    state = {"principal": Principal("peer", SimpleNamespace(peer_install_id=SENDER)), "receive": True}

    async def credentials_dep() -> Principal:
        if state["principal"] is None:
            from fastapi import HTTPException
            raise HTTPException(401, "no scope")
        return state["principal"]

    class FakeState:
        def restrictions(self):
            return restrictions.Restrictions(may_receive_credentials=state["receive"])

        def relay_consent(self):
            return state.get("consent", consent_mod.Consent(consent_mod.MODE_ALL))

    monkeypatch.setattr(config_state, "_default", FakeState())
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[routes._require_credentials] = credentials_dep
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app), state, owner_of, root, OWNER


def _body(**over: Any) -> Dict[str, Any]:
    body = {"account_key": "acme", "profile": _name(), "access_token": FAKE_TOKEN,
            "expires_at": _expiry_ms()[1], "scopes": ["user:inference"]}
    body.update(over)
    return body


def test_receive_route_answers_422_401_403_409(receive_app, tmp_path):
    client, state, owner_of, root, owner = receive_app
    url = "/api/v1/federation/pack/credentials"

    assert client.post(url, json=_body()).status_code == 200
    token_free = lambda r: FAKE_TOKEN not in r.text  # noqa: E731

    r = client.post(url, json=_body(refresh_token="x"))
    assert r.status_code == 422 and token_free(r)
    r = client.post(url, json=_body(access_token=FAKE_TOKEN + "x" * 2000))
    assert r.status_code == 422 and token_free(r)
    assert client.post(url, json=_body(expires_at=10 ** 40)).status_code == 422
    assert client.post(url, json=_body(scopes=["x" * 200])).status_code == 422

    state["principal"] = None
    assert client.post(url, json=_body()).status_code == 401

    state["principal"] = owner
    assert client.post(url, json=_body()).status_code == 403

    from types import SimpleNamespace

    from src.api.peer_auth import Principal
    state["principal"] = Principal("peer", SimpleNamespace(peer_install_id=SENDER))
    state["receive"] = False
    r = client.post(url, json=_body())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "pack_restricted"
    state["receive"] = True

    owner_of.add("acme")
    r = client.post(url, json=_body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "relay_owner_conflict"
    owner_of.clear()

    service = _service(tmp_path / "home")
    before = _seed(root, service, {"claudeAiOauth": {"refreshToken": "fake-refresh"}})
    r = client.post(url, json=_body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "relay_profile_conflict"
    assert (root / "items" / service).read_text() == before


@pytest.mark.parametrize("value", ["true", 1, "yes", "True", "on", 2, [], {}, None])
def test_receiving_credentials_cannot_be_coerced_on(value):
    from types import SimpleNamespace

    from src.api.pack_machines_routes import RestrictionsBody
    from src.core.mcp import pack_machines_tools
    from src.core.mcp.common import ToolError

    routed: List[Any] = []
    with pytest.raises(ToolError):
        pack_machines_tools._restrictions_set(SimpleNamespace(
            route=lambda *a: routed.append(a), request=None, args={"machine": "self", "may_receive_credentials": value}))
    assert routed == []
    if value is not None:
        with pytest.raises(ValidationError):
            RestrictionsBody(may_receive_credentials=value)
    for name in ("may_install_tools", "may_update_carnivore", "may_host_agents", "may_receive_projects"):
        with pytest.raises(ValidationError):
            RestrictionsBody(**{name: "yes"})
    assert RestrictionsBody(may_receive_credentials=False).may_receive_credentials is False


def test_existing_item_that_cannot_be_read_ends_not_verified_and_is_never_written(fake_security, tmp_path):
    root, exe = fake_security
    _, expiry_ms = _expiry_ms()
    home = tmp_path / "home"
    service = _service(home)
    before = _seed(root, service, {"claudeAiOauth": {"accessToken": "old", "refreshToken": "fake-refresh-value"}})
    (root / "unreadable").write_text("")
    with pytest.raises(target_side.RelayRefused) as caught:
        _receive(exe, home, expiry_ms)
    assert caught.value.code == "write_not_verified" and caught.value.status == 503
    assert (root / "items" / service).read_text() == before
    assert not any("-U" in (c["stdin"] or "").split() for c in _calls(root))


def test_revoke_route_owner_403_foreign_marker_refused_own_marker_deleted(receive_app, tmp_path):
    client, state, owner_of, root, owner = receive_app
    from types import SimpleNamespace

    from src.api.peer_auth import Principal
    url = "/api/v1/federation/pack/credentials/acme"
    service = _service(tmp_path / "home")
    state["principal"] = owner
    assert client.delete(url).status_code == 403
    state["principal"] = Principal("peer", SimpleNamespace(peer_install_id=SENDER))
    foreign = _seed(root, service, {"claudeAiOauth": {"refreshToken": "fake-refresh"}})
    r = client.delete(url)
    assert r.status_code == 200 and r.json()["removed"] is False
    assert (root / "items" / service).read_text() == foreign
    other = _seed(root, service, {"claudeAiOauth": {"accessToken": "t"}, "carnivoreRelay": {"from": "install-b"}})
    assert client.delete(url).json()["removed"] is False
    assert (root / "items" / service).read_text() == other
    (root / "items" / service).unlink()
    assert client.post("/api/v1/federation/pack/credentials", json=_body()).status_code == 200
    assert (root / "items" / service).exists()
    r = client.delete(url)
    assert r.status_code == 200 and r.json()["removed"] is True
    assert not (root / "items" / service).exists()


def test_relay_receive_marks_onboarding_done_and_touches_nothing_else(fake_security, tmp_path):
    root, exe = fake_security
    home = tmp_path / "peer-home"
    cfg = home / ".carnivore" / "accounts" / _name()
    cfg.mkdir(parents=True)
    other = {"theme": "dark", "projects": {"/w": {"hasTrustDialogAccepted": True}}}
    (cfg / ".claude.json").write_text(json.dumps(other))
    _, expiry_ms = _expiry_ms()
    _receive(exe, home, expiry_ms)
    assert json.loads((cfg / ".claude.json").read_text()) == {**other, "hasCompletedOnboarding": True}
    assert sorted(p.name for p in cfg.iterdir()) == [".claude.json", ".claude.json.bak"]
    (cfg / ".claude.json").unlink()
    _receive(exe, home, expiry_ms + 1000)
    assert json.loads((cfg / ".claude.json").read_text()) == {"hasCompletedOnboarding": True}


def test_relay_defaults_on_for_an_account_with_no_choice_and_an_explicit_off_stays_off(tmp_path):
    from src.core.pack.machines import restrictions

    db = tmp_path / "relay.db"

    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db))
        conn.isolation_level = None
        return conn

    with open_db() as conn:
        apply_pack_relay(conn)
    sent: List[str] = []

    async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        sent.append(body["account_key"])
        return 200, {"ok": True}

    relay = owner_side.Relay(open_db=open_db, peer=lambda iid: (post, [owner_side.CAP_CREDENTIALS]), notify=lambda: None,
                             self_id="iid-owner", candidates=lambda: ["peer-b"])
    when, _ = _expiry_ms()
    credential = FakeCredential(FAKE_TOKEN, when)
    with open_db() as conn:
        assert targets.effective_on(conn, "fresh") is True
    assert asyncio.run(relay.push_account("fresh", credential)) == ["peer-b"]
    with open_db() as conn:
        assert targets.effective_on(conn, "fresh") is True
        targets.set_machines(conn, "chosen", [], "iid-owner")
        assert targets.effective_on(conn, "chosen") is False
    assert asyncio.run(relay.push_account("chosen", credential)) == []
    with open_db() as conn:
        targets.set_machines(conn, "fresh", [], "iid-owner")
        assert targets.effective_on(conn, "fresh") is False
    assert asyncio.run(relay.push_account("fresh", FakeCredential(FAKE_TOKEN, when + timedelta(hours=8)))) == []
    assert sent == ["fresh"]
    assert restrictions.from_dict(None).may_receive_credentials is False


def test_relay_consent_gates_push_and_write_migrates_and_lists_pending(receive_app, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import pack_relay_consent_routes as consent_routes
    from src.api.auth import require_auth
    from src.core import config_writer
    from src.core.pack.machines import config_state, restrictions
    from src.core.pack.machines import runtime as machines_runtime
    from src.core.resource_push import topics

    client, state, _owner_of, root, _owner = receive_app
    url = "/api/v1/federation/pack/credentials"
    writes: List[str] = []
    real_write = target_side.keychain_write.write_item
    monkeypatch.setattr(target_side.keychain_write, "write_item",
                        lambda service, *a, **k: (writes.append(service), real_write(service, *a, **k))[1])

    for refused in (consent_mod.Consent(), consent_mod.Consent(consent_mod.MODE_NONE),
                    consent_mod.Consent(consent_mod.MODE_LIST, (consent_mod.offer_key(SENDER, "other"),))):
        state["consent"] = refused
        r = client.post(url, json=_body())
        assert r.status_code == 403 and r.json()["detail"]["code"] == "relay_not_accepted" and FAKE_TOKEN not in r.text
    assert writes == []
    from src.core.pack.machines import config_state as cs_mod
    looks = iter([consent_mod.Consent("all"), consent_mod.Consent("none")])
    monkeypatch.setattr(cs_mod._default, "relay_consent", lambda: next(looks))
    r = client.post(url, json=_body())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "relay_not_accepted" and writes == []
    monkeypatch.undo() if False else monkeypatch.delattr(cs_mod._default, "relay_consent")
    state["consent"] = consent_mod.Consent(consent_mod.MODE_LIST, (consent_mod.offer_key(SENDER, "acme"),))
    assert client.post("/api/v1/federation/pack/credentials", json=_body(account_key="acme2",
           profile=_name("acme2"))).status_code == 403 and writes == []

    async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        reply = client.post(url, json=body)
        return reply.status_code, reply.json()

    db = tmp_path / "relay.db"

    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db))
        conn.isolation_level = None
        return conn

    with open_db() as conn:
        apply_pack_relay(conn)
        targets.set_machines(conn, "acme", ["peer-b"], SENDER)
    published = consent_mod.published(state["consent"])
    relay = owner_side.Relay(open_db=open_db, peer=lambda iid: (post, [owner_side.CAP_CREDENTIALS]), notify=lambda: None,
                             self_id=SENDER, accepts=lambda iid, account: consent_mod.peer_accepts(published, SENDER, account))
    cred = FakeCredential(FAKE_TOKEN, _expiry_ms()[0])
    assert asyncio.run(relay.push_account("acme", cred)) == ["peer-b"] and len(writes) == 1
    assert (root / "items" / _service(tmp_path / "home")).exists()
    with open_db() as conn:
        targets.set_machines(conn, "work", ["peer-b"], SENDER)
    assert asyncio.run(relay.push_account("work", cred)) == [] and len(writes) == 1

    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    cs = config_state.ConfigState(lambda: cfg)
    cs.save_restrictions(restrictions.Restrictions(may_receive_credentials=True))
    assert cs.relay_consent() == consent_mod.Consent()
    assert cs.migrate_relay_consent() is True and cs.relay_consent().mode == "all"
    assert json.loads(cfg.read_text())["pack_machines"]["relay_consent"]["mode"] == "all"
    assert consent_mod.accepts(cs.relay_consent(), "any-peer", "any-account")
    off = tmp_path / "off.json"
    off.write_text("{}")
    cs_off = config_state.ConfigState(lambda: off)
    assert cs_off.migrate_relay_consent() is False and cs_off.relay_consent().mode is None

    from src.core.pack.machines import exchange
    cs.save_relay_consent(consent_mod.Consent("list", ("iid-a:work",), ("iid-a:work",)))
    entry = SimpleNamespace(label="hosta", snapshot={"credential_offers": [
        {"account_key": "work", "label": "Claude Code - Work"}, {"account_key": "play", "label": "Claude Code - Play"}]})
    roster = {"iid-a": entry, "iid-gone": SimpleNamespace(label="old", snapshot={"credential_offers": [
        {"account_key": "ghost", "label": "Unpaired"}]})}
    shown = offers_mod.view(roster, cs.relay_consent(), True, {"iid-a"})
    assert shown["pending"] == ["iid-a:play"] and [o["accepted"] for o in shown["offers"]] == [True, False]
    revoked_calls: List[Tuple[str, str]] = []
    monkeypatch.setattr(target_side, "revoke", lambda sender, account, **k: revoked_calls.append((sender, account)) or True)
    seen: List[str] = []
    monkeypatch.setattr(consent_routes.resource_push, "notify", lambda topic: seen.append(topic))
    pm = exchange.PackMachines(install_id="me", label="m", app_version="1", state=cs, collector=None,
                               default_master=lambda: "me", connected=lambda: [], notify=lambda *a: None)
    pm.roster.entries.update(roster)
    wired = SimpleNamespace(state=cs, runtime=pm, sync_scopes=lambda *a: None, peers=lambda: [SimpleNamespace(install_id="iid-a")])
    monkeypatch.setattr(machines_runtime, "wiring", lambda: wired)
    app = FastAPI()
    app.include_router(consent_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    owner = TestClient(app)
    path = "/api/v1/pack/relay-consent"
    assert owner.get(path).json()["pending"] == ["iid-a:play"]
    assert owner.put(path, json={"mode": "list", "accounts": []}).status_code == 422
    assert owner.put(path, json={"mode": "list", "accounts": ["iid-z:nope"]}).status_code == 422
    assert owner.put(path, json={"mode": "list", "accounts": ["iid-gone:ghost"]}).status_code == 422
    assert owner.put(path, json={"mode": "all", "accounts": ["iid-a:work"]}).status_code == 422
    assert seen == [] and revoked_calls == []
    pm.set_restrictions({"may_receive_credentials": False}, from_peer=False)
    assert cs.relay_consent().mode == "none"
    pm.set_restrictions({"may_receive_credentials": True}, from_peer=False)
    assert cs.relay_consent().mode == "all" and json.loads(cfg.read_text())["pack_machines"]["relay_consent"]["mode"] == "all"
    revoked_calls.clear()
    done = owner.put(path, json={"mode": "list", "accounts": ["iid-a:work"]})
    assert done.status_code == 200 and done.json()["pending"] == [] and seen[-1] == topics.PACK_RELAY_OFFER
    assert sorted(revoked_calls) == [("iid-a", "play"), ("iid-gone", "ghost")] and cs.restrictions().may_receive_credentials is True
    revoked_calls.clear()
    assert owner.put(path, json={"mode": "none"}).status_code == 200
    assert cs.restrictions().may_receive_credentials is False and cs.relay_consent().mode == "none"
    assert revoked_calls == [("iid-a", "work")]
    revoked_calls.clear()
    cs.save_restrictions(restrictions.Restrictions(may_receive_credentials=True))
    cs.save_relay_consent(consent_mod.Consent("all"))
    pm.set_restrictions({"may_receive_credentials": False}, from_peer=False)
    assert sorted(revoked_calls) == [("iid-a", "play"), ("iid-a", "work"), ("iid-gone", "ghost")] and cs.relay_consent().mode == "none"

    from src.api import federation_pack_gh_login_routes as gh_routes
    monkeypatch.setattr(gh_routes, "_login", lambda account, token: (True, "ok"))
    monkeypatch.setattr(config_state, "_default", cs)
    cs.save_restrictions(restrictions.Restrictions(may_receive_credentials=True))
    gh_app = FastAPI()
    gh_app.include_router(gh_routes.router, prefix="/api/v1")
    gh_app.dependency_overrides[gh_routes._require_credentials] = lambda: __import__("src.api.peer_auth", fromlist=["x"]).Principal(
        "peer", SimpleNamespace(peer_install_id=SENDER))
    gh_body = {"account": "octocat", "token": "g" * 30}
    gh_url = "/api/v1/federation/pack/gh-login"
    cs.save_relay_consent(consent_mod.Consent("list", ("iid-a:work",), ("iid-a:work",)))
    r = TestClient(gh_app).post(gh_url, json=gh_body)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "relay_not_accepted"
    cs.save_relay_consent(consent_mod.Consent("all"))
    assert TestClient(gh_app).post(gh_url, json=gh_body).status_code == 200
