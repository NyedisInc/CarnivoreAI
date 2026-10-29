
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from structlog.testing import capture_logs

from src.config.provider_accounts import (
    DEFAULT_CLAUDE_CONFIG_DIR,
    DEFAULT_CODEX_HOME,
    ProviderAccount,
)
from src.core.provider_ledger import default_login, poller_scan
from src.core.session_token_usage import account_resolve
from src.models.provider_ledger import AccountUsage


def _account(**kwargs) -> ProviderAccount:
    base = {"id": "one", "name": "One", "provider": "claude"}
    base.update(kwargs)
    return ProviderAccount(**base)


def test_the_default_pointer_matches_and_a_moved_one_does_not():
    default = _account(id="default", claude_config_dir=DEFAULT_CLAUDE_CONFIG_DIR)
    moved = _account(id="moved", claude_config_dir="~/.carnivore/accounts/work")
    matched = account_resolve.accounts_pointing_at_default(
        [default, moved], provider="claude"
    )
    assert [row.id for row in matched] == ["default"]


def test_an_unexpanded_spelling_of_the_default_still_matches():
    absolute = str(Path(DEFAULT_CLAUDE_CONFIG_DIR).expanduser())
    matched = account_resolve.accounts_pointing_at_default(
        [_account(id="abs", claude_config_dir=absolute)], provider="claude"
    )
    assert [row.id for row in matched] == ["abs"]


def test_two_rows_on_one_directory_is_ambiguous_and_names_neither():
    rows = [
        _account(id="a", claude_config_dir=DEFAULT_CLAUDE_CONFIG_DIR),
        _account(id="b", claude_config_dir=DEFAULT_CLAUDE_CONFIG_DIR),
    ]
    matched = account_resolve.accounts_pointing_at_default(rows, provider="claude")
    assert {row.id for row in matched} == {"a", "b"}
    assert (
        account_resolve.resolve_session_account(
            Path("/nonexistent/config.json"), agent_family="claude"
        )
        is None
    )


def test_the_pointer_read_is_per_provider():
    codex = _account(id="cx", provider="codex", codex_home=DEFAULT_CODEX_HOME)
    assert account_resolve.accounts_pointing_at_default([codex], provider="claude") == []
    assert [
        row.id
        for row in account_resolve.accounts_pointing_at_default(
            [codex], provider="codex"
        )
    ] == ["cx"]


def test_a_family_with_no_provider_answers_none():
    for family in ("hermes", "shell", "local", "openclaw", None, ""):
        assert (
            account_resolve.resolve_session_account(
                Path("/nonexistent/config.json"), agent_family=family
            )
            is None
        )


acme = {"accountUuid": "acct-acme", "organizationUuid": "org-acme"}
STUDIO = {"accountUuid": "acct-studio", "organizationUuid": "org-studio"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(default_login, "_IDENTITY_CACHE", {}, raising=False)
    state = {"accounts": []}
    monkeypatch.setattr(
        account_resolve.accounts_store, "list_accounts", lambda _p: state["accounts"]
    )
    monkeypatch.setattr(
        account_resolve.poller,
        "snapshot",
        lambda: SimpleNamespace(
            accounts=[
                AccountUsage(
                    id=a.id, name=a.name, provider=a.provider, credential_state="ok"
                )
                for a in poller_scan.with_auto_default(state["accounts"])
            ]
        ),
    )
    state["root"] = tmp_path
    return state


def _write_identity(path: Path, oauth) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"numStartups": 3}
    if oauth is not None:
        document["oauthAccount"] = oauth
    path.write_text(json.dumps(document))


def _profile(home, account_id: str, oauth) -> ProviderAccount:
    directory = home["root"] / ".carnivore" / "accounts" / account_id
    _write_identity(directory / ".claude.json", oauth)
    return _account(id=account_id, name=account_id, claude_config_dir=str(directory))


def _resolve():
    row = account_resolve.resolve_session_account(
        Path("/unused/config.json"), agent_family="claude"
    )
    return row.id if row is not None else None


def test_the_default_login_resolves_to_the_profile_with_its_identity(home):
    _write_identity(home["root"] / ".claude.json", acme)
    home["accounts"] = [
        _profile(home, "studio", STUDIO),
        _profile(home, "acme", acme),
    ]
    assert _resolve() == "acme"


def test_a_default_login_no_profile_matches_is_the_built_in_login(home):
    _write_identity(home["root"] / ".claude.json", {"accountUuid": "acct-other"})
    home["accounts"] = [_profile(home, "studio", STUDIO)]
    assert _resolve() == poller_scan.AUTO_DEFAULT_ACCOUNT_ID
    _write_identity(home["root"] / ".claude.json", STUDIO)
    assert _resolve() == "studio"


def test_no_configured_accounts_falls_back_to_the_auto_default_login(home):
    _write_identity(home["root"] / ".claude.json", acme)
    home["accounts"] = []
    assert _resolve() == poller_scan.AUTO_DEFAULT_ACCOUNT_ID
    home["accounts"] = [_profile(home, "acme", acme)]
    assert _resolve() == "acme"


def test_two_profiles_with_one_identity_are_ambiguous(home):
    _write_identity(home["root"] / ".claude.json", acme)
    first = _profile(home, "acme", acme)
    home["accounts"] = [first, _profile(home, "acme2", acme)]
    assert _resolve() is None
    home["accounts"] = [first]
    assert _resolve() == "acme"


def test_identity_beats_a_row_still_pointing_at_the_default_dir(home):
    pointer = _account(id="old", name="Studio", claude_config_dir=DEFAULT_CLAUDE_CONFIG_DIR)
    _write_identity(home["root"] / ".claude.json", acme)
    home["accounts"] = [pointer, _profile(home, "acme", acme)]
    assert _resolve() == "acme"
    home["accounts"] = [pointer, _profile(home, "studio", STUDIO)]
    assert _resolve() == "old"


@pytest.mark.parametrize(
    "oauth, raw",
    [
        (None, None),
        ("not-a-dict", None),
        ({"emailAddress": "a@b.c"}, None),
        (None, "{not json"),
    ],
    ids=["missing", "not-an-object", "no-uuid", "malformed-json"],
)
def test_a_default_identity_without_a_uuid_is_null_and_logged(home, oauth, raw):
    default_file = home["root"] / ".claude.json"
    if raw is None:
        _write_identity(default_file, oauth)
    else:
        default_file.write_text(raw)
    home["accounts"] = [_profile(home, "acme", acme)]
    with capture_logs() as logs:
        assert _resolve() == poller_scan.AUTO_DEFAULT_ACCOUNT_ID
    events = {entry["event"] for entry in logs}
    assert events & {
        "session_account_identity_absent",
        "session_account_identity_unreadable",
    }
    _write_identity(default_file, acme)
    os.utime(default_file, ns=(1, 2_000_000_000_000_000_000))
    assert _resolve() == "acme"


def test_an_unchanged_identity_file_is_parsed_once(home, monkeypatch):
    _write_identity(home["root"] / ".claude.json", acme)
    home["accounts"] = [_profile(home, "acme", acme)]
    calls = []
    real = default_login._parse_login_identity
    monkeypatch.setattr(
        default_login,
        "_parse_login_identity",
        lambda path: calls.append(path) or real(path),
    )
    assert _resolve() == "acme"
    assert _resolve() == "acme"
    assert len(calls) == 2


def test_an_unreadable_config_answers_none_rather_than_raising():
    assert (
        account_resolve.resolve_session_account(
            Path("/nonexistent/definitely-not-here.json"), agent_family="claude"
        )
        is None
    )
