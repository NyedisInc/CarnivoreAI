
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from src.config.provider_accounts import ProviderAccount
from src.core.account_switch.pane_account import PaneProfile, account_for_profile
from src.core.provider_ledger import default_login
from src.core.session_token_usage.account_resolve import accounts_for_default_login

SECRET = "sk-secret-token-value-123"


def _jwt(account_id: str, user: str = "u1") -> str:
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id, "chatgpt_user_id": user}}
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def _login(home: Path, account_id=None, *, jwt_id=None, user="u1") -> str:
    home.mkdir(parents=True, exist_ok=True)
    tokens = {"access_token": SECRET, "refresh_token": SECRET}
    if account_id:
        tokens["account_id"] = account_id
    if jwt_id or account_id:
        tokens["id_token"] = _jwt(jwt_id or account_id, user)
    (home / "auth.json").write_text(json.dumps({"tokens": tokens}))
    return str(home)


def _row(id: str, home: str) -> ProviderAccount:
    return ProviderAccount(id=id, name=id, provider="codex", codex_home=home)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    default_login._CODEX_ID_CACHE.clear()
    return tmp_path


def test_matching_id_resolves_and_mismatch_does_not(env):
    _login(env / ".codex", "acct-1")
    good = _row("good", _login(env / "a", "acct-1"))
    bad = _row("bad", _login(env / "b", "acct-2"))
    assert accounts_for_default_login([good, bad], provider="codex") == [good]
    assert account_for_profile([good, bad], "codex", PaneProfile(True, None)) == "good"
    assert accounts_for_default_login([bad], provider="codex") == []


def test_same_workspace_different_user_does_not_match(env):
    _login(env / ".codex", "acct-1", user="alice")
    other = _row("other", _login(env / "a", "acct-1", user="bob"))
    same = _row("same", _login(env / "b", "acct-1", user="alice"))
    assert accounts_for_default_login([other], provider="codex") == []
    assert accounts_for_default_login([other, same], provider="codex") == [same]


def test_no_user_claim_means_no_match(env):
    _login(env / ".codex", "acct-1")
    nouser = env / "a"
    nouser.mkdir()
    (nouser / "auth.json").write_text(json.dumps({"tokens": {"account_id": "acct-1", "access_token": SECRET}}))
    assert accounts_for_default_login([_row("n", str(nouser))], provider="codex") == []


def test_jwt_claim_used_when_no_top_level_id(env):
    _login(env / ".codex", jwt_id="acct-9")
    row = _row("jwt", _login(env / "a", "acct-9"))
    assert accounts_for_default_login([row], provider="codex") == [row]


def test_missing_garbage_and_malformed_answer_none(env):
    row = _row("r", _login(env / "a", "acct-1"))
    assert accounts_for_default_login([row], provider="codex") == []
    (env / ".codex").mkdir()
    (env / ".codex" / "auth.json").write_text("{not json" + SECRET)
    assert accounts_for_default_login([row], provider="codex") == []
    _login(env / ".codex", jwt_id=None)
    (env / ".codex" / "auth.json").write_text(
        json.dumps({"tokens": {"id_token": "a.b.c", "access_token": SECRET}})
    )
    assert accounts_for_default_login([row], provider="codex") == []


def test_two_accounts_with_same_id_are_ambiguous(env):
    _login(env / ".codex", "acct-1")
    rows = [_row("x", _login(env / "a", "acct-1")), _row("y", _login(env / "b", "acct-1"))]
    assert len(accounts_for_default_login(rows, provider="codex")) == 2
    assert account_for_profile(rows, "codex", PaneProfile(True, None)) is None


def test_pointer_rung_stays_first(env):
    _login(env / ".codex", "acct-1")
    pointed = _row("p", str(env / ".codex"))
    other = _row("o", _login(env / "a", "acct-1"))
    assert accounts_for_default_login([pointed, other], provider="codex") == [pointed]


def test_no_token_in_logs(env):
    _login(env / ".codex", "acct-1")
    (env / "a").mkdir()
    (env / "a" / "auth.json").write_text("{garbage " + SECRET)
    with capture_logs() as logs:
        accounts_for_default_login([_row("a", str(env / "a"))], provider="codex")
    assert logs and SECRET not in json.dumps(logs, default=str)
