
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.skill_manager import skill_extensions as he
from src.core.skill_manager.inventory import build_inventory
from src.core.skill_manager.roots import known_profiles
from src.cplugs.huddle import mcp as _huddle_mcp  # noqa: F401
from src.cplugs.huddle.guide_rev import TASK_MANAGER_GUIDE_REV


def _skill(root: Path, folder: str, extra: str) -> None:
    directory = root / folder
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\nname: {folder}\ndescription: d\n{extra}---\nbody\n", encoding="utf-8")


def _inventory(home: Path) -> dict:
    return build_inventory(
        profiles=known_profiles([], home=home, managed_root=str(home / "none")), profile_id=None, project_path=None,
        home=home, codex_home=home / ".codex", ledger_rows=[], targets_for=lambda _i: (), update_check=lambda _r: False,
        plugin_scope=dict)


def _row(inv: dict, name: str) -> dict:
    return next(loc for g in inv["skills"] if g["name"] == name for loc in g["locations"])


@pytest.fixture(autouse=True)
def _fresh():
    he.reset_for_tests()
    yield
    he.reset_for_tests()


def test_behind_current_and_no_extends(tmp_path):
    skills = tmp_path / ".claude" / "skills"
    _skill(skills, "old-addon", f"extends: huddle\nguide_rev: {TASK_MANAGER_GUIDE_REV - 1}\n")
    _skill(skills, "new-addon", f"extends: huddle\nguide_rev: {TASK_MANAGER_GUIDE_REV}\n")
    _skill(skills, "other", f"guide_rev: {TASK_MANAGER_GUIDE_REV - 1}\n")
    _skill(skills, "unrev", "extends: huddle\n")
    inv = _inventory(tmp_path)
    old = _row(inv, "old-addon")["behind_rules"]
    assert old["written_for"] == TASK_MANAGER_GUIDE_REV - 1 and old["current"] == TASK_MANAGER_GUIDE_REV
    assert [c["rev"] for c in old["changes"]] == [TASK_MANAGER_GUIDE_REV]
    assert _row(inv, "new-addon")["behind_rules"] is None
    assert _row(inv, "other")["behind_rules"] is None
    assert _row(inv, "unrev")["behind_rules"]["written_for"] == 0
    assert he.stale_extensions("huddle", home=tmp_path) == [
        {"name": "old-addon", "written_for": TASK_MANAGER_GUIDE_REV - 1, "current": TASK_MANAGER_GUIDE_REV},
        {"name": "unrev", "written_for": 0, "current": TASK_MANAGER_GUIDE_REV}]


def test_a_rescan_drops_a_fixed_or_removed_addon(tmp_path):
    skills = tmp_path / ".claude" / "skills"
    _skill(skills, "addon", "extends: huddle\nguide_rev: 1\n")
    _inventory(tmp_path)
    assert [r["name"] for r in he.stale_extensions("huddle", home=tmp_path)] == ["addon"]
    (skills / "addon" / "SKILL.md").write_text(
        f"---\nname: addon\ndescription: d\nextends: huddle\nguide_rev: {TASK_MANAGER_GUIDE_REV}\n---\nb\n", encoding="utf-8")
    _inventory(tmp_path)
    assert he.stale_extensions("huddle", home=tmp_path) == []


def test_a_rev_change_recomputes_without_a_rescan(tmp_path):
    _skill(tmp_path / ".claude" / "skills", "addon", f"extends: huddle\nguide_rev: {TASK_MANAGER_GUIDE_REV}\n")
    _inventory(tmp_path)
    assert he.stale_extensions("huddle", home=tmp_path) == []
    assert he.stale_extensions("huddle", TASK_MANAGER_GUIDE_REV + 1, home=tmp_path) == [
        {"name": "addon", "written_for": TASK_MANAGER_GUIDE_REV, "current": TASK_MANAGER_GUIDE_REV + 1}]


def test_a_process_that_never_rescanned_seeds_from_the_personal_roots(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.provider_accounts.MANAGED_ROOT", tmp_path / "accounts")
    _skill(tmp_path / ".claude" / "skills", "addon", "extends: huddle\nguide_rev: 1\n")
    assert [r["name"] for r in he.stale_extensions("huddle", home=tmp_path)] == ["addon"]


@pytest.mark.parametrize("front,expected", [
    ({"extends": "Huddle", "guide_rev": 3}, ("huddle", 3)),
    ({"extends": "huddle", "guide_rev": "3"}, ("huddle", 3)),
    ({"extends": "huddle", "guide_rev": True}, ("huddle", None)),
    ({"extends": 5, "guide_rev": -1}, (None, None)),
    ({}, (None, None)),
])
def test_parse_extension(front, expected):
    assert he.parse_extension(front) == expected


def test_an_unregistered_extends_is_never_flagged(tmp_path):
    _skill(tmp_path / ".claude" / "skills", "x", "extends: other\nguide_rev: 1\n")
    assert _row(_inventory(tmp_path), "x")["behind_rules"] is None
    assert he.stale_extensions("other", home=tmp_path) == []
