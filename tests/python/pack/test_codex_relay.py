
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from pydantic import ValidationError

from src.api.federation_pack_credentials_routes import CodexCredentialBody
from src.core.pack.relay import codex_target, offers as offers_mod, owner_side, targets
from src.core.pack.relay.ddl import apply_pack_relay
from src.core.pack.relay.target_side import RelayRefused

SENDER = "iid-owner"


def _jwt(claims: Dict[str, Any]) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def _tokens(hours: float = 8.0) -> Tuple[str, str, int]:
    exp = int(time.time() + hours * 3600)
    return (_jwt({"exp": exp}), _jwt({"exp": int(time.time()) + 3600,
                                      "https://api.openai.com/auth": {"chatgpt_account_id": "acc-1"}}), exp * 1000)


def _recv(home: Path, *, key: str = "work", sender: str = SENDER, hours: float = 8.0, **kw: Any) -> int:
    at, it, ms = _tokens(hours)
    return codex_target.receive_codex(sender, key, codex_target.codex_relay_profile_name(key, sender), at, it, "acc-1",
                                      kw.pop("expires_ms", ms), home=home, **kw)


def _auth(home: Path, key: str = "work", sender: str = SENDER) -> Path:
    return Path(codex_target.codex_relay_profile_dir(key, sender, home)) / "auth.json"


def test_receiver_writes_access_only_file_0600_in_a_0700_home(tmp_path):
    _recv(tmp_path)
    path = _auth(tmp_path)
    doc = json.loads(path.read_text())
    assert doc["tokens"]["refresh_token"] == "" and doc["carnivoreRelay"] == {"from": SENDER}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.parent.name.endswith("-work-relay-codex") and not path.parent.name.endswith("-work-relay")
    assert codex_target.find_codex_relay_profile("work", tmp_path) == str(path.parent)
    _recv(tmp_path)
    assert not list(path.parent.glob(".auth-*"))


def test_receiver_refuses_real_login_foreign_marker_bad_shapes_and_bounds(tmp_path):
    home = Path(codex_target.codex_relay_profile_dir("work", SENDER, tmp_path))
    home.mkdir(parents=True)
    real = '{"tokens":{"access_token":"a","id_token":"b","refresh_token":"REAL"}}'
    (home / "auth.json").write_text(real)
    with pytest.raises(RelayRefused) as err:
        _recv(tmp_path)
    assert err.value.status == 409 and (home / "auth.json").read_text() == real
    (home / "auth.json").write_text("not json")
    with pytest.raises(RelayRefused):
        _recv(tmp_path)
    (home / "auth.json").unlink()
    _recv(tmp_path, sender=SENDER)
    doc = json.loads((home / "auth.json").read_text())
    doc["carnivoreRelay"]["from"] = "someone-else"
    (home / "auth.json").write_text(json.dumps(doc))
    with pytest.raises(RelayRefused) as err:
        _recv(tmp_path)
    assert err.value.code == "relay_peer_conflict"
    (home / "auth.json").unlink()
    at, it, ms = _tokens()
    name = codex_target.codex_relay_profile_name("work", SENDER)
    base: Dict[str, Any] = dict(sender_install_id=SENDER, account_key="work", profile=name, access_token=at, id_token=it,
                                account_id="acc-1", expires_at_ms=ms, home=tmp_path)
    for patch in ({"access_token": "not a jwt"}, {"id_token": "x" * 9000}, {"account_id": "bad id!"},
                  {"profile": "ab12-work-relay-codex"}, {"account_key": "Bad Key"},
                  {"expires_at_ms": int((time.time() + 10) * 1000)},
                  {"expires_at_ms": int((time.time() + 31 * 86400) * 1000)},
                  {"expires_at_ms": ms + 60_000}):
        with pytest.raises(RelayRefused):
            codex_target.receive_codex(**{**base, **patch})
    with pytest.raises(RelayRefused) as err:
        codex_target.receive_codex(**base, reserved_names={name})
    assert err.value.status == 409
    with pytest.raises(RelayRefused) as err:
        codex_target.receive_codex(**base, authorize=lambda: False)
    assert err.value.status == 403 and not (home / "auth.json").exists()
    assert codex_target.receive_codex(**{**base, "expires_at_ms": ms}) == ms


def test_revoke_deletes_only_this_senders_relay_file(tmp_path):
    _recv(tmp_path)
    assert codex_target.revoke_codex("someone-else", "work", home=tmp_path) is False and _auth(tmp_path).exists()
    assert codex_target.revoke_codex(SENDER, "work", home=tmp_path) is True and not _auth(tmp_path).exists()
    home = _auth(tmp_path).parent
    home.mkdir(exist_ok=True)
    _auth(tmp_path).write_text('{"tokens":{"refresh_token":"REAL"}}')
    assert codex_target.revoke_codex(SENDER, "work", home=tmp_path) is False and _auth(tmp_path).exists()


def test_body_model_refuses_a_refresh_token_and_any_extra_field():
    at, it, ms = _tokens()
    ok = {"account_key": "work", "profile": "p", "access_token": at, "id_token": it, "account_id": "a", "expires_at": ms}
    CodexCredentialBody.model_validate(ok)
    for extra in ("refresh_token", "last_refresh", "oauth_provenance", "login_owner_id", "scopes"):
        with pytest.raises(ValidationError):
            CodexCredentialBody.model_validate({**ok, extra: "x"})


def test_launch_env_helper_points_refresh_and_revoke_at_a_dead_loopback():
    env = codex_target.codex_relay_env("/h")
    assert set(env) == {"CODEX_HOME", "CODEX_REFRESH_TOKEN_URL_OVERRIDE", "CODEX_REVOKE_TOKEN_URL_OVERRIDE"}
    assert env["CODEX_HOME"] == "/h" and all(env[k].startswith("https://127.0.0.1:1/") for k in env if k != "CODEX_HOME")


@dataclass
class FakeCodexCredential:
    access_token: str
    id_token: Optional[str]
    account_id: Optional[str]
    expires_at: datetime
    plan: Optional[str] = "plus"
    refresh_token: str = "fake-refresh-token-must-never-leave"


def _owner(tmp_path: Path, caps: List[str]):
    db = tmp_path / "relay.db"

    def open_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db))
        conn.isolation_level = None
        return conn

    with open_db() as conn:
        apply_pack_relay(conn)
    sent: List[Tuple[str, str, Dict[str, Any]]] = []

    async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        sent.append((method, path, body or {}))
        return 200, {"ok": True}

    return owner_side.Relay(open_db=open_db, peer=lambda iid: (post, caps), notify=lambda: None, self_id=SENDER), open_db, sent


def test_owner_pushes_codex_to_its_own_path_with_exactly_the_field_set(tmp_path):
    relay, open_db, sent = _owner(tmp_path, [owner_side.CAP_CREDENTIALS_CODEX])
    at, it, ms = _tokens()
    cred = FakeCodexCredential(at, it, "acc-1", datetime.fromtimestamp(ms / 1000, tz=timezone.utc))
    with open_db() as conn:
        targets.set_machines(conn, "work", ["peer-b"], SENDER, "codex")
        assert targets.list_all(conn)[0].target_profile == codex_target.codex_relay_profile_name("work", SENDER)
    assert asyncio.run(relay.push_account("work", cred, "codex")) == ["peer-b"]
    method, path, body = sent[0]
    assert (method, path) == ("POST", owner_side.CODEX_CREDENTIALS_PATH)
    assert set(body) == {"account_key", "profile", "access_token", "id_token", "account_id", "expires_at", "plan"}
    assert cred.refresh_token not in json.dumps(body)
    CodexCredentialBody.model_validate(body)
    asyncio.run(relay.revoke("work", ["peer-b"], "codex"))
    assert sent[-1][:2] == ("DELETE", f"{owner_side.CODEX_CREDENTIALS_PATH}/work")


def test_owner_skips_a_target_without_the_codex_capability_and_an_owner_without_an_id_token(tmp_path):
    relay, open_db, sent = _owner(tmp_path, [owner_side.CAP_CREDENTIALS])
    at, it, ms = _tokens()
    when = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    with open_db() as conn:
        targets.set_machines(conn, "work", ["peer-b"], SENDER, "codex")
    assert asyncio.run(relay.push_account("work", FakeCodexCredential(at, it, "acc-1", when), "codex")) == []
    assert sent == []
    with open_db() as conn:
        assert targets.list_all(conn)[0].state == "on"
    relay2, open_db2, sent2 = _owner(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path,
                                     [owner_side.CAP_CREDENTIALS_CODEX])
    with open_db2() as conn:
        targets.set_machines(conn, "work", ["peer-b"], SENDER, "codex")
    assert asyncio.run(relay2.push_account("work", FakeCodexCredential(at, None, "acc-1", when), "codex")) == []
    assert sent2 == []


def test_offers_carry_provider_and_consent_keeps_it():
    from src.core.pack.relay import consent as consent_mod
    cleaned = consent_mod.clean_offers([{"account_key": "w", "label": "L", "provider": "codex"},
                                        {"account_key": "c", "label": "C", "provider": "evil"}, {"account_key": "d", "label": "D"}])
    assert cleaned == [{"account_key": "w", "label": "L", "provider": "codex"}, {"account_key": "c", "label": "C"},
                       {"account_key": "d", "label": "D"}]
    assert callable(offers_mod.revoke_keys)


def test_revoke_keys_removes_a_codex_relay_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _recv(tmp_path)
    assert offers_mod.revoke_keys([f"{SENDER}:work"]) == 1 and not _auth(tmp_path).exists()


def _codex_bins() -> List[str]:
    found = shutil.which("codex")
    return [found] if found else []


@pytest.mark.skipif(not _codex_bins(), reason="the codex CLI is not installed on this machine: the real-boundary check cannot run")
def test_real_codex_parses_the_relay_file_with_no_network(tmp_path):
    _recv(tmp_path)
    home = str(_auth(tmp_path).parent)
    env = {**os.environ, **codex_target.codex_relay_env(home)}
    env.pop("OPENAI_API_KEY", None)
    done = subprocess.run([_codex_bins()[0], "login", "status"], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, (done.stdout + done.stderr)[-300:]
    assert "chatgpt" in (done.stdout + done.stderr).lower()
    assert json.loads(_auth(tmp_path).read_text())["tokens"]["refresh_token"] == ""
