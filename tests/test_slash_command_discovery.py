from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import slash_command_discovery as scd


@pytest.fixture()
def fake_claude_home(tmp_path, monkeypatch):
    home = tmp_path / "fake-claude-home"
    home.mkdir()
    monkeypatch.setattr(scd, "CLAUDE_HOME", home)
    return home



def test_command_file_namespaced_by_subdirectory(fake_claude_home):
    commands_dir = fake_claude_home / "commands" / "my"
    commands_dir.mkdir(parents=True)
    (commands_dir / "cb.md").write_text("# Circle Back Command\n\n**Description**: resync moment\n")

    found = scd.discover_user_scope()
    assert len(found) == 1
    assert found[0].command == "/my:cb"
    assert found[0].type == "user-command"


def test_command_file_without_subdirectory_has_no_namespace(fake_claude_home):
    commands_dir = fake_claude_home / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "deploy.md").write_text("# Deploy\n\n**Description**: ship it\n")

    found = scd.discover_user_scope()
    assert found[0].command == "/deploy"


def test_matches_real_seven_file_my_namespace_layout(fake_claude_home):
    my_dir = fake_claude_home / "commands" / "my"
    my_dir.mkdir(parents=True)
    names = ["cb", "email-assistant", "gogs-add", "powershell-standards", "project-init", "qnap", "reevaluate"]
    for name in names:
        (my_dir / f"{name}.md").write_text(f"# {name}\n\n**Description**: does {name}\n")
    (my_dir / "gogs-add.md.backup-20260516-113837").write_text("stale backup, not a command")

    found = scd.discover_user_scope()
    commands = sorted(c.command for c in found)
    assert commands == sorted(f"/my:{n}" for n in names)



def test_command_and_skill_both_create_same_slash_name(fake_claude_home):
    (fake_claude_home / "commands").mkdir()
    (fake_claude_home / "commands" / "deploy.md").write_text("# Deploy\n\n**Description**: via command file\n")

    skill_dir = fake_claude_home / "skills" / "deploy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: via skill frontmatter\n---\n\n# Deploy\n"
    )

    found = scd.discover_user_scope()
    by_type = {c.type: c for c in found}
    assert by_type["user-command"].command == "/deploy"
    assert by_type["user-command"].description == "via command file"
    assert by_type["user-skill"].command == "/deploy"
    assert by_type["user-skill"].description == "via skill frontmatter"



def test_skill_frontmatter_description_used_when_present(fake_claude_home):
    skill_dir = fake_claude_home / "skills" / "docker-management"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: docker-management\ndescription: "Manages the docker fleet."\n---\n\n# Docker\n'
    )
    found = scd.discover_user_scope()
    assert found[0].description == "Manages the docker fleet."


def test_command_falls_back_to_description_line_convention(fake_claude_home):
    commands_dir = fake_claude_home / "commands"
    commands_dir.mkdir()
    (commands_dir / "reevaluate.md").write_text(
        "# Reevaluate Command\n\n**Description**: Spawn subagents to review code.\n"
    )
    found = scd.discover_user_scope()
    assert found[0].description == "Spawn subagents to review code."


def test_command_falls_back_to_heading_when_no_description_line(fake_claude_home):
    commands_dir = fake_claude_home / "commands"
    commands_dir.mkdir()
    (commands_dir / "bare.md").write_text("# Just A Heading\n\nSome body text with no marker.\n")
    found = scd.discover_user_scope()
    assert found[0].description == "Just A Heading"


def test_empty_file_falls_back_to_filename(fake_claude_home):
    commands_dir = fake_claude_home / "commands"
    commands_dir.mkdir()
    (commands_dir / "empty.md").write_text("")
    found = scd.discover_user_scope()
    assert found[0].description == "empty"



def test_missing_commands_and_skills_dirs_yield_empty_list(fake_claude_home):
    assert scd.discover_user_scope() == []


def test_missing_project_path_yields_empty_list():
    assert scd.discover_project_scope("") == []
    assert scd.discover_project_scope(None) == []



def test_project_scope_scans_project_dot_claude(tmp_path):
    project = tmp_path / "myproject"
    (project / ".claude" / "commands").mkdir(parents=True)
    (project / ".claude" / "commands" / "release.md").write_text(
        "# Release\n\n**Description**: cut a release\n"
    )
    found = scd.discover_project_scope(str(project))
    assert len(found) == 1
    assert found[0].command == "/release"
    assert found[0].type == "project-command"



def test_plugin_scope_groups_by_plugin_name_from_cache_path(fake_claude_home):
    version_dir = fake_claude_home / "plugins" / "cache" / "thedotmack" / "claude-mem" / "12.1.5"
    skills_dir = version_dir / "skills" / "do"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("---\ndescription: Execute a plan\n---\n")

    by_plugin = scd.discover_plugin_scope()
    assert list(by_plugin.keys()) == ["claude-mem"]
    assert by_plugin["claude-mem"][0].command == "/do"
    assert by_plugin["claude-mem"][0].type == "plugin-skill"


def test_hook_only_plugin_produces_no_group(fake_claude_home):
    version_dir = fake_claude_home / "plugins" / "cache" / "somemarket" / "hookplugin" / "1.0.0"
    (version_dir / "hooks").mkdir(parents=True)
    (version_dir / "hooks" / "pre-commit.sh").write_text("#!/bin/sh\n")

    by_plugin = scd.discover_plugin_scope()
    assert by_plugin == {}



def test_group_user_scope_splits_root_and_namespaced(fake_claude_home):
    commands_dir = fake_claude_home / "commands"
    (commands_dir / "my").mkdir(parents=True)
    (commands_dir / "deploy.md").write_text("# Deploy\n\n**Description**: root level\n")
    (commands_dir / "my" / "cb.md").write_text("# CB\n\n**Description**: namespaced\n")

    found = scd.discover_user_scope()
    groups = scd._group_user_scope(found)
    ids = [g.id for g in groups]
    assert "user" in ids
    assert "user:my" in ids
    user_group = next(g for g in groups if g.id == "user")
    my_group = next(g for g in groups if g.id == "user:my")
    assert user_group.commands[0].command == "/deploy"
    assert my_group.commands[0].command == "/my:cb"


def test_build_command_groups_never_hand_curated_reflects_disk(fake_claude_home, monkeypatch):
    monkeypatch.setattr(scd, "_load_scraped_commands", lambda: [])
    commands_dir = fake_claude_home / "commands"
    commands_dir.mkdir()
    cmd_file = commands_dir / "temp.md"
    cmd_file.write_text("# Temp\n\n**Description**: will be removed\n")

    groups = scd.build_command_groups()
    flat = [c.command for g in groups for c in g.commands]
    assert "/temp" in flat

    cmd_file.unlink()
    groups_after = scd.build_command_groups()
    flat_after = [c.command for g in groups_after for c in g.commands]
    assert "/temp" not in flat_after


def test_command_groups_to_dict_shape(fake_claude_home, monkeypatch):
    monkeypatch.setattr(scd, "_load_scraped_commands", lambda: [
        {"command": "/help", "args": "", "description": "Show help", "type": "builtin", "alias_of": None},
    ])
    groups = scd.build_command_groups()
    payload = scd.command_groups_to_dict(groups)
    builtin_group = next(g for g in payload if g["id"] == "builtin")
    assert builtin_group["label"] == "built-in commands"
    assert builtin_group["commands"] == [
        {"command": "/help", "args": "", "description": "Show help", "type": "builtin", "alias_of": None}
    ]




def test_discover_user_scope_defaults_to_the_module_root(fake_claude_home):
    (fake_claude_home / "skills" / "defaulted").mkdir(parents=True)
    (fake_claude_home / "skills" / "defaulted" / "SKILL.md").write_text("x\n")

    assert [c.command for c in scd.discover_user_scope()] == ["/defaulted"]


def test_discover_user_scope_reads_the_root_it_is_given(tmp_path, fake_claude_home):
    (fake_claude_home / "skills" / "from-the-default").mkdir(parents=True)
    (fake_claude_home / "skills" / "from-the-default" / "SKILL.md").write_text("x\n")

    given = tmp_path / "given-home"
    (given / "skills" / "from-the-argument").mkdir(parents=True)
    (given / "skills" / "from-the-argument" / "SKILL.md").write_text("x\n")
    (given / "commands").mkdir()
    (given / "commands" / "a-command.md").write_text("# a command\n")

    found = sorted(c.command for c in scd.discover_user_scope(given))

    assert found == ["/a-command", "/from-the-argument"]


def test_the_codex_twin_lists_skills_from_the_root_it_is_given(tmp_path):
    codex_skills = tmp_path / "codex" / "skills"
    (codex_skills / "installed").mkdir(parents=True)
    (codex_skills / "installed" / "SKILL.md").write_text("a codex skill\n")

    found = scd.discover_codex_user_scope(codex_skills)

    assert [c.command for c in found] == ["/installed"]
    assert found[0].type == "codex-skill"


def test_the_codex_twin_defaults_to_the_codex_home_env_var(tmp_path, monkeypatch):
    codex_home = tmp_path / "somewhere-else"
    (codex_home / "skills" / "env-rooted").mkdir(parents=True)
    (codex_home / "skills" / "env-rooted" / "SKILL.md").write_text("x\n")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert [c.command for c in scd.discover_codex_user_scope()] == ["/env-rooted"]


def test_the_codex_twin_is_empty_when_codex_is_not_installed(tmp_path):
    assert scd.discover_codex_user_scope(tmp_path / "no-codex") == []


def test_a_dot_directory_is_skipped_by_the_skill_scan(tmp_path):
    skills = tmp_path / "skills"
    (skills / ".system" / "bundled").mkdir(parents=True)
    (skills / ".system" / "bundled" / "SKILL.md").write_text("codex internal\n")
    (skills / ".carnivore-trash" / "displaced-20260915").mkdir(parents=True)
    (skills / ".carnivore-trash" / "displaced-20260915" / "SKILL.md").write_text("old\n")
    (skills / "real-one").mkdir(parents=True)
    (skills / "real-one" / "SKILL.md").write_text("mine\n")

    found = [c.command for c in scd.discover_codex_user_scope(skills)]

    assert found == ["/real-one"]


def test_build_command_groups_passes_both_roots_through(tmp_path, monkeypatch):
    monkeypatch.setattr(scd, "_load_scraped_commands", lambda: [])
    monkeypatch.setattr(scd, "discover_plugin_scope", lambda root=None: {})

    claude_home = tmp_path / "claude-home"
    (claude_home / "skills" / "claude-side").mkdir(parents=True)
    (claude_home / "skills" / "claude-side" / "SKILL.md").write_text("x\n")

    codex_skills = tmp_path / "codex" / "skills"
    (codex_skills / "codex-side").mkdir(parents=True)
    (codex_skills / "codex-side" / "SKILL.md").write_text("x\n")

    groups = scd.build_command_groups(
        claude_home=claude_home, codex_skills_root=codex_skills
    )
    by_id = {g.id: [c.command for c in g.commands] for g in groups}

    assert by_id["user"] == ["/claude-side"]
    assert by_id["codex"] == ["/codex-side"]


def test_an_empty_codex_root_produces_no_group(tmp_path, monkeypatch):
    monkeypatch.setattr(scd, "_load_scraped_commands", lambda: [])
    monkeypatch.setattr(scd, "discover_plugin_scope", lambda root=None: {})

    claude_home = tmp_path / "claude-home"
    (claude_home / "skills" / "only-claude").mkdir(parents=True)
    (claude_home / "skills" / "only-claude" / "SKILL.md").write_text("x\n")

    groups = scd.build_command_groups(
        claude_home=claude_home, codex_skills_root=tmp_path / "no-codex"
    )

    assert "codex" not in {g.id for g in groups}
