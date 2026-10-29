
from __future__ import annotations

import os
import secrets
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_hta_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_hta_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.core.sessions.hook_token_authority import HookTokenAuthority

SESSION = "ses_probe"
PANE = "cloude_probe"


@pytest.fixture()
def authority(tmp_path: Path) -> HookTokenAuthority:
    return HookTokenAuthority(lambda: tmp_path)


class _StubSettings:

    def __init__(self, state: Path) -> None:
        self._state = state
        self.port = 5001

    def get_state_dir(self) -> Path:
        return self._state

    def get_pinned_themes_path(self) -> Path:
        return self._state / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._state / "unread_state.json"

    def get_session_metadata_path(self) -> Path:
        return self._state / "session_metadata.json"

    @property
    def log_directory(self) -> str:
        return str(self._state / "logs")


@pytest.fixture()
def manager(monkeypatch, tmp_path: Path) -> SessionManager:
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr(
        "src.core.session_manager.settings", _StubSettings(tmp_path)
    )
    return SessionManager()




def test_the_manager_holds_no_second_copy_of_the_token_table(manager):
    assert isinstance(manager.hook_tokens, HookTokenAuthority)
    for name in (
        "_hook_tokens",
        "_hook_tmux_names",
        "_hook_tokens_durable",
        "_superseded_hook_tokens",
    ):
        assert not hasattr(manager, name), (
            f"SessionManager still carries {name}; the state was copied, "
            "not moved, and the two will disagree the moment one is written"
        )


def test_a_mint_through_the_authority_is_visible_through_the_manager(manager):
    token = manager.hook_tokens.mint(SESSION, tmux_name=PANE)
    assert manager.hook_tokens.tokens[SESSION] == token
    assert manager.hook_tokens.get(SESSION) == token
    assert manager.hook_tokens.get(SESSION) == token


def test_a_deletion_through_one_reference_is_visible_through_the_other(manager):
    table = manager.hook_tokens.tokens
    manager.hook_tokens.mint(SESSION, tmux_name=PANE)
    assert SESSION in table

    table.pop(SESSION)
    assert manager.hook_tokens.get(SESSION) is None
    assert manager.hook_tokens.get(SESSION) is None


def test_the_tmux_name_map_is_one_object_too(manager):
    names = manager.hook_tokens.tmux_names
    manager.hook_tokens.mint(SESSION, tmux_name=PANE)
    assert names.get(SESSION) == PANE

    manager.hook_tokens.keep(SESSION, tmux_name="cloude_moved")
    assert names.get(SESSION) == "cloude_moved"
    assert manager.hook_tokens.name_for(SESSION) == "cloude_moved"




def test_keep_does_not_rotate_the_secret(authority):
    original = authority.mint(SESSION, tmux_name=PANE)
    kept = authority.keep(SESSION, tmux_name="cloude_other")
    assert kept == original
    assert authority.get(SESSION) == original
    assert authority.get(SESSION) == original


def test_keep_refuses_an_id_that_holds_no_token(authority):
    assert authority.keep("ses_never_seen", tmux_name=PANE) is None
    assert authority.get("ses_never_seen") is None


def test_a_mint_replaces_the_held_token(authority):
    first = authority.mint(SESSION, tmux_name=PANE)
    second = authority.mint(SESSION, tmux_name=PANE)
    assert first != second
    assert authority.get(SESSION) == second




def test_the_store_answers_the_minted_value_and_no_other(authority):
    token = authority.mint(SESSION)
    forged = "x" * len(token)

    assert authority.get(SESSION) == token
    assert authority.get(SESSION) != forged
    assert authority.get("ses_never_minted") is None


def test_an_unreadable_owned_list_keeps_every_token(authority, tmp_path):
    authority.mint(SESSION, tmux_name=PANE)
    (tmp_path / "session_metadata.json").write_text("{ this is not json")
    assert authority.gc() == []
    assert authority.get(SESSION) is not None


def test_the_gc_drops_a_token_whose_pane_is_no_longer_owned(authority, tmp_path):
    authority.mint(SESSION, tmux_name=PANE)
    authority.mint("ses_still_here", tmux_name="cloude_live")
    (tmp_path / "session_metadata.json").write_text(
        '{"owned_tmux_sessions": ["cloude_live"]}'
    )
    assert authority.gc() == [SESSION]
    assert authority.get(SESSION) is None
    assert authority.get("ses_still_here") is not None


def test_a_token_with_no_recorded_pane_is_kept(authority, tmp_path):
    authority.mint("ses_no_name")
    (tmp_path / "session_metadata.json").write_text(
        '{"owned_tmux_sessions": ["cloude_live"]}'
    )
    assert authority.gc() == []
    assert authority.get("ses_no_name") is not None


def test_a_token_survives_a_restart(tmp_path):
    first = HookTokenAuthority(lambda: tmp_path)
    token = first.mint(SESSION, tmux_name=PANE)

    second = HookTokenAuthority(lambda: tmp_path)
    assert second.get(SESSION) == token
    assert second.name_for(SESSION) == PANE
    assert second.get(SESSION) == token
