
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ir_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ir_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import slash_command_discovery as scd
from src.core.live_install_roots import LiveInstallRoots
from src.core.sessions.ports import Target
from src.core.skills import targets as skill_targets
from src.core.skills.roots import (
    ROOT_ABSENT,
    ROOT_IS_SYMLINK,
    ROOT_PARENT_IS_SYMLINK,
    ROOT_OK,
    ROOT_STATES,
    TARGET_EXISTS,
    TARGET_IS_SYMLINK,
    UnsafeInstallName,
    check_root,
    check_roots,
    target_dir,
)


class _StateOnlySettings:

    def __init__(self, state: Path) -> None:
        self._state = state

    def pinned_themes_path(self) -> Path:
        return self._state / "pinned_themes.json"

    def log_buffer_size(self) -> int:
        return 1

    def state_dir(self) -> Path:
        return self._state

    def session_metadata_path(self) -> Path:
        return self._state / "session_metadata.json"


@pytest.fixture()
def roots(tmp_path) -> LiveInstallRoots:
    return LiveInstallRoots(settings_reader=_StateOnlySettings(tmp_path / "state"))


def _target(leaf: Path, harness: str = "claude") -> Target:
    return Target(harness=harness, leaf_dir=leaf)




def test_global_skill_targets_are_the_two_harness_roots(roots):
    found = roots.targets_for("skill", "global", None)

    assert [t.harness for t in found] == ["claude", "codex"]
    assert found[0].leaf_dir == Path.home() / ".claude" / "skills"
    assert found[1].leaf_dir == Path.home() / ".agents" / "skills"


def test_codex_home_env_var_moves_the_legacy_root_only(roots, monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "elsewhere"))

    found = roots.targets_for("skill", "global", None)
    legacy = roots.legacy_targets_for("skill", "global", None)

    assert found[1].leaf_dir == Path.home() / ".agents" / "skills"
    assert [t.leaf_dir for t in legacy] == [tmp_path / "elsewhere" / "skills"]
    assert (
        roots.trash_dir("codex", "global", None)
        == Path.home() / ".agents" / ".carnivore-trash"
    )


def test_a_blank_codex_home_is_treated_as_unset(roots, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "   ")

    legacy = roots.legacy_targets_for("skill", "global", None)

    assert [t.leaf_dir for t in legacy] == [Path.home() / ".codex" / "skills"]


def test_the_codex_global_root_is_never_the_older_codex_home_root(roots):
    found = roots.targets_for("skill", "global", None)
    legacy = roots.legacy_targets_for("skill", "global", None)

    assert all(".codex" not in t.leaf_dir.parts for t in found)
    assert len(legacy) == 1
    assert roots.legacy_targets_for("skill", "project", "/tmp/x") == ()
    assert roots.legacy_targets_for("theme", "global", None) == ()


def test_the_trash_is_a_sibling_of_each_skills_root(roots):
    found = {t.harness: t.leaf_dir for t in roots.targets_for("skill", "global", None)}

    for harness, skills_root in found.items():
        trash = roots.trash_dir(harness, "global", None)
        assert trash.parent == skills_root.parent
        assert trash.name == ".carnivore-trash"


def test_a_project_trash_is_a_sibling_of_the_project_root_not_of_home(
    roots, tmp_path
):
    project = tmp_path / "repo"

    claude_trash = roots.trash_dir("claude", "project", str(project))
    codex_trash = roots.trash_dir("codex", "project", str(project))

    assert claude_trash == project / ".claude" / ".carnivore-trash"
    assert codex_trash == project / ".agents" / ".carnivore-trash"
    for trash in (claude_trash, codex_trash):
        assert Path.home() not in trash.parents, (
            f"{trash} is under the user's home, so a project folder would "
            "be displaced out of the repository it belongs to"
        )


def test_every_trash_is_a_sibling_of_the_root_of_its_own_scope(roots, tmp_path):
    for scope, project_path in (("global", None), ("project", str(tmp_path / "r"))):
        for target in roots.targets_for("skill", scope, project_path):
            trash = roots.trash_dir(target.harness, scope, project_path)
            assert trash.parent == target.leaf_dir.parent
            assert trash.name == ".carnivore-trash"


def test_a_project_scope_trash_still_refuses_a_missing_project_path(roots):
    with pytest.raises(ValueError, match="project scope requires"):
        roots.trash_dir("claude", "project", None)


def test_a_global_scope_trash_still_refuses_a_project_path(roots):
    with pytest.raises(ValueError, match="global scope takes no project_path"):
        roots.trash_dir("claude", "global", "/somewhere")


def test_the_state_dir_paths_come_from_the_settings_port(roots, tmp_path):
    assert roots.staging_dir() == tmp_path / "state" / "skills" / ".staging"
    assert roots.pending_dir() == tmp_path / "state" / "skills" / ".pending"


def test_the_required_manifest_for_a_skill_is_skill_md(roots):
    assert roots.required_manifest("skill") == "SKILL.md"




def test_project_skill_targets_are_dot_claude_and_dot_agents(roots, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()

    found = roots.targets_for("skill", "project", str(project))

    assert [t.harness for t in found] == ["claude", "codex"]
    assert found[0].leaf_dir == project / ".claude" / "skills"
    assert found[1].leaf_dir == project / ".agents" / "skills"


def test_a_project_path_is_canonicalised_with_realpath(roots, tmp_path):
    real = tmp_path / "real-project"
    real.mkdir()
    link = tmp_path / "linked-project"
    link.symlink_to(real, target_is_directory=True)

    through_link = roots.targets_for("skill", "project", str(link))
    direct = roots.targets_for("skill", "project", str(real))

    assert [t.leaf_dir for t in through_link] == [t.leaf_dir for t in direct]
    assert str(real.resolve()) in str(through_link[0].leaf_dir)


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_project_scope_without_a_path_is_refused(roots, bad):
    with pytest.raises(ValueError, match="project scope requires"):
        roots.targets_for("skill", "project", bad)


def test_global_scope_with_a_project_path_is_refused(roots, tmp_path):
    with pytest.raises(ValueError, match="global scope takes no project_path"):
        roots.targets_for("skill", "global", str(tmp_path))


@pytest.mark.parametrize(
    "kind,scope",
    [("bundle", "global"), ("skill", "everywhere")],
)
def test_an_unknown_kind_or_scope_is_refused_and_never_defaulted(roots, kind, scope):
    with pytest.raises(ValueError):
        roots.targets_for(kind, scope, None)


def test_a_plugin_resolves_to_one_claude_root_inside_the_skills_directory(roots):
    targets = roots.targets_for("plugin", "global", None)

    assert [target.harness for target in targets] == ["claude"]
    assert targets[0].leaf_dir.name == "skills"
    assert "plugins" not in targets[0].leaf_dir.parts


def test_an_unknown_harness_is_refused_by_trash_and_listing(roots):
    with pytest.raises(ValueError, match="unknown harness"):
        roots.trash_dir("gemini", "global", None)
    with pytest.raises(ValueError, match="unknown harness"):
        roots.root_listing("gemini")




@pytest.mark.parametrize(
    "name",
    [".system", ".carnivore-trash", ".hidden", ".system/nested"],
)
def test_a_name_whose_first_segment_starts_with_a_dot_is_refused(tmp_path, name):
    target = _target(tmp_path / "skills")

    with pytest.raises(UnsafeInstallName, match="starts with a dot"):
        target_dir(target, name)


@pytest.mark.parametrize(
    "name",
    ["", "   ", "/etc/passwd", "../escape", "a/../../b", "a//b", "a\\b", "a\0b"],
)
def test_a_name_that_could_escape_the_root_is_refused(tmp_path, name):
    target = _target(tmp_path / "skills")

    with pytest.raises(UnsafeInstallName):
        target_dir(target, name)


def test_a_dotted_segment_that_is_not_first_is_allowed(tmp_path):
    target = _target(tmp_path / "skills")

    assert target_dir(target, "ok/.inner") == tmp_path / "skills" / "ok" / ".inner"


def test_a_plain_name_composes_under_the_root(tmp_path):
    target = _target(tmp_path / "skills")

    assert target_dir(target, "sme") == tmp_path / "skills" / "sme"


def test_check_root_applies_the_name_rule_before_touching_the_filesystem(tmp_path):
    target = _target(tmp_path / "nothing-here")

    with pytest.raises(UnsafeInstallName):
        check_root(target, ".system")




def test_an_absent_root_is_named_not_created(tmp_path):
    root = tmp_path / "no-such-root"
    target = _target(root)

    assert check_root(target, "sme").state == ROOT_ABSENT
    assert not root.exists()


def test_a_broken_symlink_root_is_a_symlink_and_not_an_absence(tmp_path):
    root = tmp_path / "dangling"
    root.symlink_to(tmp_path / "gone", target_is_directory=True)
    target = _target(root)

    assert check_root(target, "sme").state == ROOT_IS_SYMLINK


def test_a_symlinked_root_is_refused_rather_than_followed(tmp_path):
    real = tmp_path / "real-skills"
    real.mkdir()
    root = tmp_path / "linked-skills"
    root.symlink_to(real, target_is_directory=True)

    assert check_root(_target(root), "sme").state == ROOT_IS_SYMLINK


def test_a_symlinked_harness_directory_above_the_root_is_refused(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "skills").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    claude = home / ".claude"
    claude.symlink_to(elsewhere, target_is_directory=True)
    root = claude / "skills"
    assert root.is_dir(), "the link resolves, which is exactly the problem"
    assert not root.is_symlink(), "the LEAF is not a link; the segment above is"

    check = check_root(_target(root), "sme")

    assert check.state == ROOT_PARENT_IS_SYMLINK
    assert check.is_writable is False
    assert list((elsewhere / "skills").iterdir()) == [], "a query writes nothing"


def test_a_broken_link_above_the_root_is_still_a_link_and_not_an_absence(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    claude = home / ".claude"
    claude.symlink_to(tmp_path / "gone", target_is_directory=True)

    assert check_root(_target(claude / "skills"), "sme").state == (
        ROOT_PARENT_IS_SYMLINK
    )


def test_the_walk_stops_at_the_root_s_parent_and_not_at_the_home(tmp_path):
    real_home = tmp_path / "real-home"
    (real_home / ".claude" / "skills").mkdir(parents=True)
    linked_home = tmp_path / "linked-home"
    linked_home.symlink_to(real_home, target_is_directory=True)

    check = check_root(_target(linked_home / ".claude" / "skills"), "sme")

    assert check.state == ROOT_OK
    assert check.is_writable is True


def test_an_existing_target_is_named_so_the_caller_can_offer_a_choice(tmp_path):
    root = tmp_path / "skills"
    (root / "sme").mkdir(parents=True)

    assert check_root(_target(root), "sme").state == TARGET_EXISTS


def test_a_symlinked_target_is_told_apart_from_a_real_one(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (root / "sme").symlink_to(tmp_path / "elsewhere", target_is_directory=True)

    assert check_root(_target(root), "sme").state == TARGET_IS_SYMLINK


def test_a_clean_root_with_a_free_name_is_ok(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()

    check = check_root(_target(root), "sme")

    assert check.state == ROOT_OK
    assert check.is_writable is True


def test_every_state_in_the_published_tuple_is_reachable(tmp_path):
    produced = set()

    absent = tmp_path / "absent"
    produced.add(check_root(_target(absent), "sme").state)

    linked = tmp_path / "linked"
    (tmp_path / "linked-real").mkdir()
    linked.symlink_to(tmp_path / "linked-real", target_is_directory=True)
    produced.add(check_root(_target(linked), "sme").state)

    clean = tmp_path / "clean"
    clean.mkdir()
    produced.add(check_root(_target(clean), "sme").state)

    (clean / "taken").mkdir()
    produced.add(check_root(_target(clean), "taken").state)

    (tmp_path / "away").mkdir()
    (clean / "aliased").symlink_to(tmp_path / "away", target_is_directory=True)
    produced.add(check_root(_target(clean), "aliased").state)

    (tmp_path / "over-there" / "skills").mkdir(parents=True)
    above = tmp_path / "above"
    above.symlink_to(tmp_path / "over-there", target_is_directory=True)
    produced.add(check_root(_target(above / "skills"), "sme").state)

    assert produced == set(ROOT_STATES)


def test_the_root_check_carries_the_root_it_is_about(tmp_path):
    claude_root = tmp_path / "c" / "skills"
    codex_root = tmp_path / "x" / "skills"
    claude_root.mkdir(parents=True)

    checks = check_roots(
        [_target(claude_root, "claude"), _target(codex_root, "codex")], "sme"
    )

    assert [(c.harness, c.state) for c in checks] == [
        ("claude", ROOT_OK),
        ("codex", ROOT_ABSENT),
    ]
    assert checks[0].root == claude_root
    assert checks[1].root == codex_root


def test_one_missing_root_does_not_reduce_the_other_to_a_verdict(tmp_path):
    present = tmp_path / "present"
    present.mkdir()

    checks = check_roots(
        [_target(present, "claude"), _target(tmp_path / "gone", "codex")], "sme"
    )

    assert [c.is_writable for c in checks] == [True, False]




def test_a_folder_moved_to_trash_is_no_longer_listed_as_a_skill(tmp_path):
    home = tmp_path / "home" / ".claude"
    skills = home / "skills"
    (skills / "doomed").mkdir(parents=True)
    (skills / "doomed" / "SKILL.md").write_text("doomed skill\n")

    before = [c.command for c in scd.discover_user_scope(home)]
    assert "/doomed" in before

    skill_targets.move_to_trash(
        skills / "doomed", home / ".carnivore-trash", "20260915T000000"
    )

    after = [c.command for c in scd.discover_user_scope(home)]
    assert after == []
    assert (home / ".carnivore-trash" / "doomed-20260915T000000" / "SKILL.md").is_file()


def test_a_dot_directory_under_skills_is_never_listed(tmp_path):
    home = tmp_path / "home" / ".claude"
    skills = home / "skills"
    (skills / ".system" / "codex-internal").mkdir(parents=True)
    (skills / ".system" / "codex-internal" / "SKILL.md").write_text("internal\n")
    (skills / "mine").mkdir(parents=True)
    (skills / "mine" / "SKILL.md").write_text("mine\n")

    found = [c.command for c in scd.discover_user_scope(home)]

    assert found == ["/mine"]
