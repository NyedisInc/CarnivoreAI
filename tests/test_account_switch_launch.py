
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from src.config import settings
from src.config.provider_accounts import ProviderAccount, managed_dir_for
from src.core.account_switch import launch_env, shared_links, store
from src.core.provider_ledger import accounts_store, managed_profiles
from src.core.tmux_command_batch import environment_commands
from tests.helpers.claude_profile import write_claude_profile


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    projects = tmp_path / ".claude" / "projects" / "-proj"
    projects.mkdir(parents=True)
    (projects / "conv-1.jsonl").write_text('{"type":"user"}\n')
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    (tmp_path / ".codex" / "sessions").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def config(home, monkeypatch):
    path = home / "config.json"
    path.write_text(json.dumps({"agents": {}}))
    for account_id in ("work", "play"):
        managed_profiles.ensure_managed_dir(account_id)
        write_claude_profile(managed_dir_for(account_id))
        accounts_store.upsert_account(path, ProviderAccount(
            id=account_id, name=account_id, provider="claude",
            claude_config_dir=managed_dir_for(account_id), managed=True,
        ))
    managed_profiles.ensure_managed_dir("cx")
    accounts_store.upsert_account(path, ProviderAccount(
        id="cx", name="cx", provider="codex",
        codex_home=managed_dir_for("cx"), managed=True,
    ))
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    return path


def test_nothing_is_injected_until_an_account_is_chosen(config):
    assert launch_env.account_env(config) == {}
    assert launch_env.apply_to_new_pane({"A": "1"}, {}) == {"A": "1", "CLAUDE_CONFIG_DIR": None}


def test_a_workspace_value_the_user_set_is_kept(config):
    assert launch_env.apply_to_new_pane({"CLAUDE_CONFIG_DIR": "/mine"}, {}) == {"CLAUDE_CONFIG_DIR": "/mine"}


def test_a_manual_switch_changes_the_new_session_env(config, home):
    store.set_active(config, "claude", "work")
    env = launch_env.account_env(config)
    assert env == {"CLAUDE_CONFIG_DIR": managed_dir_for("work")}
    store.set_active(config, "claude", "play")
    assert launch_env.account_env(config) == {"CLAUDE_CONFIG_DIR": managed_dir_for("play")}


def test_the_create_path_merges_the_active_account_into_the_pane_env(config):
    store.set_active(config, "claude", "work")
    merged = asyncio.run(launch_env.new_pane_env({"CLOUDECODE_SESSION_ID": "s1"}))
    assert merged == {"CLOUDECODE_SESSION_ID": "s1", "CLAUDE_CONFIG_DIR": managed_dir_for("work")}


def test_a_codex_pointer_launches_nothing_while_codex_is_not_switchable(config):
    store.set_active(config, "codex", "cx")
    assert launch_env.account_env(config) == {}


def test_a_pointer_to_another_providers_account_is_not_honoured(config):
    store.set_active(config, "claude", "cx")
    assert launch_env.account_env(config) == {"CLAUDE_CONFIG_DIR": None}


def test_a_stale_pointer_removes_the_variable(config):
    store.set_active(config, "claude", "gone")
    assert launch_env.account_env(config) == {"CLAUDE_CONFIG_DIR": None}


def test_a_profile_without_the_shared_settings_is_never_used(config, home):
    own = Path(managed_dir_for("work")) / "settings.json"
    own.write_text("{}")
    store.set_active(config, "claude", "work")
    assert launch_env.account_env(config) == {}


def test_the_default_directory_is_removed_never_set(config, home):
    accounts_store.upsert_account(config, ProviderAccount(
        id="primary", name="primary", provider="claude", claude_config_dir="~/.claude",
    ))
    store.set_active(config, "claude", "primary")
    env = launch_env.account_env(config)
    assert env == {"CLAUDE_CONFIG_DIR": None}
    assert launch_env.apply_to_new_pane({"CLAUDE_CONFIG_DIR": "/stale", "A": "1"}, env) == {
        "CLAUDE_CONFIG_DIR": None,
        "A": "1",
    }


def test_a_restart_removes_the_variable_with_set_environment_r():
    commands = environment_commands("=s:", {"A": "1", "CLAUDE_CONFIG_DIR": None})
    assert commands == [
        ("set-environment", "-t", "=s:", "A", "1"),
        ("set-environment", "-t", "=s:", "-r", "CLAUDE_CONFIG_DIR"),
    ]


def test_the_restart_env_keeps_the_control_variables_and_adds_the_account(config):
    store.set_active(config, "claude", "work")
    env = asyncio.run(launch_env.respawn_pane_env({"CLOUDECODE_SESSION_ID": "s1"}))
    assert env == {"CLOUDECODE_SESSION_ID": "s1", "CLAUDE_CONFIG_DIR": managed_dir_for("work")}




def test_switching_links_the_profiles_transcripts_to_the_shared_ones(config, home):
    store.set_active(config, "claude", "work")
    launch_env.account_env(config)
    linked = Path(managed_dir_for("work")) / "projects"
    assert linked.is_symlink()
    assert (linked / "-proj" / "conv-1.jsonl").read_text() == '{"type":"user"}\n'
    assert (Path(managed_dir_for("work")) / "settings.json").is_symlink()
    assert not (Path(managed_dir_for("work")) / ".claude.json").is_symlink()


def test_an_existing_directory_is_never_overwritten_and_blocks_the_switch(config, home):
    own = Path(managed_dir_for("work")) / "projects"
    own.mkdir()
    (own / "mine.jsonl").write_text("x")
    store.set_active(config, "claude", "work")
    assert launch_env.account_env(config) == {}
    assert not own.is_symlink()
    assert (own / "mine.jsonl").read_text() == "x"


def test_an_existing_file_is_never_overwritten(config, home):
    own = Path(managed_dir_for("work")) / "settings.json"
    own.write_text('{"mine": true}')
    report = shared_links.ensure_shared_links(managed_dir_for("work"), "claude", managed=True)
    assert report.entries["settings.json"] == shared_links.PRESENT
    assert report.entries["projects"] == shared_links.LINKED
    assert own.read_text() == '{"mine": true}' and not own.is_symlink()


def test_an_unmanaged_profile_is_never_written_into(home):
    mine = home / ".claude-work"
    mine.mkdir()
    report = shared_links.ensure_shared_links(str(mine), "claude", managed=False)
    assert report.resume_safe is False
    assert os.listdir(mine) == []


def test_removing_a_profile_never_reaches_through_its_links(config, home):
    shared_links.ensure_shared_links(managed_dir_for("work"), "claude", managed=True)
    outcome = managed_profiles.remove_managed_dir("work")
    assert outcome.status == "removed"
    assert (home / ".claude" / "projects" / "-proj" / "conv-1.jsonl").exists()
    assert (home / ".claude" / "settings.json").exists()


def test_the_status_registry_is_linked_even_when_it_did_not_exist_yet(config, home):
    report = shared_links.ensure_shared_links(managed_dir_for("work"), "claude", managed=True)
    assert report.resume_safe is True
    assert (home / ".claude" / "sessions").is_dir()
    assert (Path(managed_dir_for("work")) / "sessions").is_symlink()




def _shared_extras(home):
    (home / ".claude" / "keybindings.json").write_text('{"bindings": []}')
    (home / ".claude" / "ide").mkdir()
    plans = home / ".claude" / "plans"
    plans.mkdir()
    (plans / "shared-plan.md").write_text("shared")
    return plans


def test_keybindings_plans_and_ide_are_linked_like_the_rest(config, home):
    _shared_extras(home)
    report = shared_links.ensure_shared_links(managed_dir_for("work"), "claude", managed=True)
    profile = Path(managed_dir_for("work"))
    for entry in ("keybindings.json", "plans", "ide"):
        assert report.entries[entry] == shared_links.LINKED
        assert os.path.realpath(profile / entry) == os.path.realpath(home / ".claude" / entry)
    assert (profile / "plans" / "shared-plan.md").read_text() == "shared"


def test_a_profiles_own_plans_are_moved_in_then_linked_and_nothing_is_lost(config, home):
    plans = _shared_extras(home)
    (plans / "clash.md").write_text("the shared one")
    (plans / "same.md").write_text("identical")
    own = Path(managed_dir_for("work")) / "plans"
    own.mkdir()
    (own / "unique.md").write_text("only in the profile")
    (own / "clash.md").write_text("the profile's one")
    (own / "same.md").write_text("identical")
    (own / "nested").mkdir()
    (own / "nested" / "deep.md").write_text("deep")

    report = shared_links.ensure_shared_links(managed_dir_for("work"), "claude", managed=True)

    assert report.entries["plans"] == shared_links.LINKED and own.is_symlink()
    assert (plans / "unique.md").read_text() == "only in the profile"
    assert (plans / "clash.md").read_text() == "the shared one"
    assert (plans / "clash.work.md").read_text() == "the profile's one"
    assert (plans / "same.md").read_text() == "identical"
    assert (plans / "nested" / "deep.md").read_text() == "deep"
    assert (plans / "shared-plan.md").read_text() == "shared"
    assert sorted(p.name for p in plans.iterdir()) == [
        "clash.md", "clash.work.md", "nested", "same.md", "shared-plan.md", "unique.md",
    ]


def test_a_second_clash_gets_its_own_name(config, home):
    plans = _shared_extras(home)
    (plans / "a.md").write_text("1")
    (plans / "a.work.md").write_text("2")
    own = Path(managed_dir_for("work")) / "plans"
    own.mkdir()
    (own / "a.md").write_text("3")
    shared_links.ensure_shared_links(managed_dir_for("work"), "claude", managed=True)
    assert [(plans / n).read_text() for n in ("a.md", "a.work.md", "a.work-2.md")] == ["1", "2", "3"]


def test_plans_are_migrated_even_when_the_shared_directory_did_not_exist(config, home):
    own = Path(managed_dir_for("work")) / "plans"
    own.mkdir()
    (own / "p.md").write_text("mine")
    report = shared_links.ensure_shared_links(managed_dir_for("work"), "claude", managed=True)
    assert report.entries["plans"] == shared_links.LINKED
    assert (home / ".claude" / "plans" / "p.md").read_text() == "mine"


def test_a_move_that_fails_leaves_the_rest_in_place_and_does_not_link(config, home, monkeypatch):
    plans = _shared_extras(home)
    own = Path(managed_dir_for("work")) / "plans"
    own.mkdir()
    (own / "a.md").write_text("a")
    (own / "b.md").write_text("b")
    real = shared_links._move_no_overwrite

    def fail_on_b(src, dest):
        if src.endswith("b.md"):
            raise PermissionError(src)
        real(src, dest)

    monkeypatch.setattr(shared_links, "_move_no_overwrite", fail_on_b)
    report = shared_links.ensure_shared_links(managed_dir_for("work"), "claude", managed=True)
    assert report.entries["plans"] == shared_links.PRESENT and not own.is_symlink()
    assert (plans / "a.md").read_text() == "a" and (own / "b.md").read_text() == "b"


def test_a_profiles_own_keybindings_file_is_never_overwritten(config, home):
    _shared_extras(home)
    own = Path(managed_dir_for("work")) / "keybindings.json"
    own.write_text('{"mine": true}')
    report = shared_links.ensure_shared_links(managed_dir_for("work"), "claude", managed=True)
    assert report.entries["keybindings.json"] == shared_links.PRESENT
    assert own.read_text() == '{"mine": true}' and not own.is_symlink()


def test_a_restart_is_refused_when_the_active_profile_is_unusable(config, home):
    from src.core.account_switch import pane_account

    (Path(managed_dir_for("work")) / "settings.json").write_text("{}")
    store.set_active(config, "claude", "work")
    assert launch_env.account_env(config) == {}

    async def elsewhere(socket, name, variable):
        return pane_account.PaneProfile(readable=True, value=None)

    async def already(socket, name, variable):
        return pane_account.PaneProfile(readable=True, value=managed_dir_for("work"))

    refusal = asyncio.run(launch_env.restart_refusal("s", "n", config_path=config, read_profile=elsewhere))
    assert refusal == launch_env.UNUSABLE_DETAIL
    assert asyncio.run(launch_env.restart_refusal("s", "n", config_path=config, read_profile=already)) is None


def test_no_refusal_when_the_active_profile_is_usable(config, home):
    from src.core.account_switch import pane_account

    async def elsewhere(socket, name, variable):
        return pane_account.PaneProfile(readable=True, value=None)

    store.set_active(config, "claude", "work")
    assert asyncio.run(launch_env.restart_refusal("s", "n", config_path=config, read_profile=elsewhere)) is None
