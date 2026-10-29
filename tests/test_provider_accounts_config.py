
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import structlog.testing
from pydantic import ValidationError

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pac_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pac_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.auth_loader import load
from src.config.provider_accounts import (
    DEFAULT_CLAUDE_CONFIG_DIR,
    DEFAULT_CODEX_HOME,
    PROVIDER_ACCOUNTS_KEY,
    ProviderAccount,
    ProviderAccountsConfig,
)
from src.config.summary import settings_summary
from src.core import config_writer, ui_preferences
from src.core.provider_ledger import accounts_store

CLAUDE_ACCOUNT = {
    "id": "max-main",
    "name": "Max main",
    "provider": "claude",
    "claude_config_dir": "~/.claude",
}

CODEX_ACCOUNT = {
    "id": "codex-plus",
    "name": "Codex plus",
    "provider": "codex",
    "codex_home": "~/.codex",
}


def _write_config(tmp_path: Path, **top_level) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"config_version": 5, **top_level}))
    return path




def test_a_valid_claude_account_keeps_its_values() -> None:
    account = ProviderAccount(**CLAUDE_ACCOUNT)
    assert account.id == "max-main"
    assert account.name == "Max main"
    assert account.provider == "claude"
    assert account.claude_config_dir == "~/.claude"


def test_a_token_key_is_refused_rather_than_carried() -> None:
    for key in ("token", "access_token", "refresh_token", "oauth_token"):
        with pytest.raises(ValidationError):
            ProviderAccount(**{**CLAUDE_ACCOUNT, key: "sk-ant-oat01-notreal"})


def test_no_declared_field_reads_like_a_credential() -> None:
    for name in ProviderAccount.model_fields:
        assert not ui_preferences.is_secret_name(name), name


def test_the_paths_default_to_the_harness_defaults() -> None:
    claude = ProviderAccount(id="a", name="A", provider="claude")
    codex = ProviderAccount(id="b", name="B", provider="codex")
    assert claude.claude_config_dir == DEFAULT_CLAUDE_CONFIG_DIR == "~/.claude"
    assert codex.codex_home == DEFAULT_CODEX_HOME == "~/.codex"


def test_a_path_is_stored_exactly_as_it_was_given() -> None:
    account = ProviderAccount(
        id="work", name="Work", provider="claude",
        claude_config_dir="~/.claude-work",
    )
    assert account.claude_config_dir == "~/.claude-work"


@pytest.mark.parametrize(
    "bad_id",
    ["", "Max-Main", "max_main", "max main", "max.main", "max-main\n"],
)
def test_an_id_that_is_not_a_lowercase_slug_is_refused(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        ProviderAccount(**{**CLAUDE_ACCOUNT, "id": bad_id})


@pytest.mark.parametrize("good_id", ["a", "max-main", "codex2", "a-1-b"])
def test_a_lowercase_slug_id_is_accepted(good_id: str) -> None:
    assert ProviderAccount(**{**CLAUDE_ACCOUNT, "id": good_id}).id == good_id


@pytest.mark.parametrize("bad_name", ["", "   "])
def test_an_empty_display_name_is_refused(bad_name: str) -> None:
    with pytest.raises(ValidationError):
        ProviderAccount(**{**CLAUDE_ACCOUNT, "name": bad_name})


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProviderAccount(**{**CLAUDE_ACCOUNT, "provider": "gemini"})


def test_a_claude_account_must_carry_a_config_dir() -> None:
    with pytest.raises(ValidationError):
        ProviderAccount(**{**CLAUDE_ACCOUNT, "claude_config_dir": "  "})


def test_a_codex_account_must_carry_a_codex_home() -> None:
    with pytest.raises(ValidationError):
        ProviderAccount(**{**CODEX_ACCOUNT, "codex_home": ""})


def test_a_claude_account_is_not_refused_for_a_blank_codex_home() -> None:
    account = ProviderAccount(**{**CLAUDE_ACCOUNT, "codex_home": ""})
    assert account.provider == "claude"




def test_the_block_defaults_to_no_accounts() -> None:
    assert ProviderAccountsConfig().accounts == []


def test_two_accounts_may_not_share_an_id() -> None:
    with pytest.raises(ValidationError):
        ProviderAccountsConfig(
            accounts=[CLAUDE_ACCOUNT, {**CODEX_ACCOUNT, "id": CLAUDE_ACCOUNT["id"]}]
        )


def test_two_accounts_with_different_ids_are_accepted() -> None:
    block = ProviderAccountsConfig(accounts=[CLAUDE_ACCOUNT, CODEX_ACCOUNT])
    assert [a.id for a in block.accounts] == ["max-main", "codex-plus"]


def test_the_block_refuses_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        ProviderAccountsConfig(accounts=[], tokens={"max-main": "sk-notreal"})




def test_the_block_reaches_the_loaded_auth_config(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path, **{PROVIDER_ACCOUNTS_KEY: {"accounts": [CLAUDE_ACCOUNT]}}
    )
    config = load(path, totp_secret="t", jwt_secret="j")
    assert [a.id for a in config.provider_accounts.accounts] == ["max-main"]


def test_a_config_without_the_block_still_loads(tmp_path: Path) -> None:
    config = load(_write_config(tmp_path), totp_secret="t", jwt_secret="j")
    assert config.provider_accounts.accounts == []


def test_a_mangled_block_costs_that_block_and_logs(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path, **{PROVIDER_ACCOUNTS_KEY: ["not", "a", "mapping"]}
    )
    with structlog.testing.capture_logs() as captured:
        config = load(path, totp_secret="t", jwt_secret="j")
    assert config.provider_accounts.accounts == []
    assert any(
        entry["event"] == "invalid_provider_accounts_config_block"
        for entry in captured
    )


def test_a_mangled_block_logs_key_names_and_no_values(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        **{PROVIDER_ACCOUNTS_KEY: {"accounts": [], "token": "sk-ant-oat01-notreal"}},
    )
    with structlog.testing.capture_logs() as captured:
        load(path, totp_secret="t", jwt_secret="j")
    rendered = json.dumps(captured)
    assert "invalid_provider_accounts_config_block" in rendered
    assert "sk-ant-oat01-notreal" not in rendered




def _summary(accounts: list) -> dict:
    from src.config.auth import AuthConfig

    config = AuthConfig(
        totp_secret="t",
        jwt_secret="j",
        provider_accounts=ProviderAccountsConfig(accounts=accounts),
    )
    return settings_summary(
        config,
        host="0.0.0.0",
        port=8000,
        families=[],
        bound_host="0.0.0.0",
    )


def test_the_summary_renders_the_accounts_with_their_paths() -> None:
    payload = _summary([CLAUDE_ACCOUNT, CODEX_ACCOUNT])
    rendered = payload["provider_accounts"]["accounts"]
    assert [row["id"] for row in rendered] == ["max-main", "codex-plus"]
    assert rendered[0]["claude_config_dir"] == "~/.claude"
    assert rendered[1]["codex_home"] == "~/.codex"


def test_the_summary_renders_only_the_declared_fields() -> None:
    payload = _summary([CLAUDE_ACCOUNT])
    declared = set(ProviderAccount.model_fields)
    for row in payload["provider_accounts"]["accounts"]:
        assert set(row) <= declared
        for key in row:
            assert not ui_preferences.is_secret_name(key), key


def test_the_summary_of_an_unconfigured_install_is_an_empty_list() -> None:
    assert _summary([])["provider_accounts"]["accounts"] == []




def test_the_block_name_is_refused_by_name_as_well() -> None:
    assert ui_preferences.is_secret_name(PROVIDER_ACCOUNTS_KEY) is True


def test_an_ordinary_preference_name_is_not_refused_by_name() -> None:
    assert ui_preferences.is_secret_name("theme") is False




def test_listing_a_config_with_no_block_is_empty(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    assert accounts_store.list_accounts(path) == []
    assert PROVIDER_ACCOUNTS_KEY not in json.loads(path.read_text())


@pytest.mark.parametrize("garbage", [["a"], "text", 7, None, {"accounts": "text"}])
def test_listing_a_mangled_block_is_empty(tmp_path: Path, garbage) -> None:
    path = _write_config(tmp_path, **{PROVIDER_ACCOUNTS_KEY: garbage})
    assert accounts_store.list_accounts(path) == []


def test_adding_an_account_commits_it(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    status, accounts = accounts_store.upsert_account(
        path, ProviderAccount(**CLAUDE_ACCOUNT)
    )
    assert status == config_writer.COMMITTED
    assert [a.id for a in accounts] == ["max-main"]
    assert [a.id for a in accounts_store.list_accounts(path)] == ["max-main"]


def test_adding_the_same_account_twice_writes_nothing(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    accounts_store.upsert_account(path, ProviderAccount(**CLAUDE_ACCOUNT))
    before = path.read_text()
    status, _ = accounts_store.upsert_account(path, ProviderAccount(**CLAUDE_ACCOUNT))
    assert status == config_writer.UNCHANGED
    assert path.read_text() == before


def test_upserting_a_known_id_replaces_it_in_place(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    accounts_store.upsert_account(path, ProviderAccount(**CLAUDE_ACCOUNT))
    accounts_store.upsert_account(path, ProviderAccount(**CODEX_ACCOUNT))
    status, accounts = accounts_store.upsert_account(
        path, ProviderAccount(**{**CLAUDE_ACCOUNT, "name": "Renamed"})
    )
    assert status == config_writer.COMMITTED
    assert [(a.id, a.name) for a in accounts] == [
        ("max-main", "Renamed"),
        ("codex-plus", "Codex plus"),
    ]


def test_removing_an_account_commits(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    accounts_store.upsert_account(path, ProviderAccount(**CLAUDE_ACCOUNT))
    accounts_store.upsert_account(path, ProviderAccount(**CODEX_ACCOUNT))
    status, accounts = accounts_store.remove_account(path, "max-main")
    assert status == config_writer.COMMITTED
    assert [a.id for a in accounts] == ["codex-plus"]


def test_removing_an_unknown_account_writes_nothing(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    accounts_store.upsert_account(path, ProviderAccount(**CLAUDE_ACCOUNT))
    before = path.read_text()
    status, accounts = accounts_store.remove_account(path, "nope")
    assert status == config_writer.UNCHANGED
    assert [a.id for a in accounts] == ["max-main"]
    assert path.read_text() == before


def test_a_write_leaves_the_rest_of_the_document_alone(tmp_path: Path) -> None:
    path = _write_config(tmp_path, notifications={"enabled": True}, template_path="x")
    accounts_store.upsert_account(path, ProviderAccount(**CLAUDE_ACCOUNT))
    data = json.loads(path.read_text())
    assert data["notifications"] == {"enabled": True}
    assert data["template_path"] == "x"
    assert data["config_version"] == 5


def test_what_lands_on_disk_carries_no_credential_shaped_key(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    accounts_store.upsert_account(path, ProviderAccount(**CLAUDE_ACCOUNT))
    block = json.loads(path.read_text())[PROVIDER_ACCOUNTS_KEY]
    for row in block["accounts"]:
        for key in row:
            assert not ui_preferences.is_secret_name(key), key


def test_a_write_logs_the_id_and_no_path_secrets(tmp_path: Path) -> None:
    path = _write_config(tmp_path)
    with structlog.testing.capture_logs() as captured:
        accounts_store.upsert_account(path, ProviderAccount(**CLAUDE_ACCOUNT))
    events = [entry["event"] for entry in captured]
    assert "provider_account_upserted" in events




def test_a_row_written_before_this_change_is_not_managed() -> None:
    account = ProviderAccount(**CLAUDE_ACCOUNT)
    assert account.managed is False


def test_a_row_written_before_this_change_has_no_colour() -> None:
    assert ProviderAccount(**CLAUDE_ACCOUNT).color is None


def test_a_managed_row_says_so() -> None:
    account = ProviderAccount(**{**CLAUDE_ACCOUNT, "managed": True})
    assert account.managed is True


def test_a_lowercase_six_digit_hex_colour_is_kept() -> None:
    account = ProviderAccount(**{**CLAUDE_ACCOUNT, "color": "#8b5cf6"})
    assert account.color == "#8b5cf6"


@pytest.mark.parametrize(
    "bad_color",
    [
        "#8B5CF6",
        "#8b5cf",
        "#8b5cf66",
        "8b5cf6",
        "#ghijkl",
        "violet",
        "",
        "#abc",
        "#8b5cf6\n",
    ],
)
def test_a_colour_that_is_not_the_stored_shape_is_refused(bad_color: str) -> None:
    with pytest.raises(ValidationError):
        ProviderAccount(**{**CLAUDE_ACCOUNT, "color": bad_color})


def test_the_two_new_fields_do_not_weaken_the_token_refusal() -> None:
    with pytest.raises(ValidationError):
        ProviderAccount(
            **{**CLAUDE_ACCOUNT, "managed": True, "color": "#8b5cf6", "token": "x"}
        )


def test_both_new_fields_survive_a_round_trip_through_the_store(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"projects": []}))
    accounts_store.upsert_account(
        path,
        ProviderAccount(
            **{**CLAUDE_ACCOUNT, "managed": True, "color": "#8b5cf6"}
        ),
    )
    stored = accounts_store.list_accounts(path)[0]
    assert (stored.managed, stored.color) == (True, "#8b5cf6")


def test_resubmitting_the_same_managed_row_is_still_unchanged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"projects": []}))
    account = ProviderAccount(**{**CLAUDE_ACCOUNT, "managed": True})
    accounts_store.upsert_account(path, account)
    status, _ = accounts_store.upsert_account(path, account)
    assert status == config_writer.UNCHANGED


def test_the_summary_renders_the_two_new_fields() -> None:
    payload = _summary([{**CLAUDE_ACCOUNT, "managed": True, "color": "#8b5cf6"}])
    row = payload["provider_accounts"]["accounts"][0]
    assert row["managed"] is True
    assert row["color"] == "#8b5cf6"
