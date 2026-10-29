
from __future__ import annotations

from src.cplugs.huddle import guide_rev, mcp
from src.cplugs.huddle.guide_rev import GUIDE_PATH, TASK_MANAGER_GUIDE_CHANGELOG, TASK_MANAGER_GUIDE_HASH, TASK_MANAGER_GUIDE_REV, guide_hash, guide_text
from src.core.mcp import instructions
from src.core.skills import bundled_install
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401

def test_the_rev_is_a_positive_int():
    assert isinstance(TASK_MANAGER_GUIDE_REV, int) and TASK_MANAGER_GUIDE_REV >= 1


def test_every_huddle_answer_carries_guide_rev(manager):
    store = huddle_store(manager)
    item = store.add("all", "work", actor="joe")["id"]
    for tool, args in (
        ("task_manager_tasks_list", {"list": "all"}),
        ("task_manager_changes", {"since": 0}),
        ("task_manager_reply", {"item": item, "text": "hello", "kind": "info"}),
        ("task_manager_update", {"item": item, "state": "working"}),
    ):
        ok, out = call(manager, tool, args)
        assert ok, out
        assert out["guide_rev"] == TASK_MANAGER_GUIDE_REV, tool


def test_the_instructions_name_the_guide_tool_and_the_rev_rule_within_budget():
    text = instructions.guide(None, channel=True)
    assert "huddle: call task_manager_guide before your first huddle write except task_manager_progress_set and task_manager_reply; re-read it when guide_rev rises" in text
    assert "skill" not in text.split("huddle:")[1].split("\n")[0]
    assert len(text) <= instructions.MAX_CHARS


def test_the_changelog_ends_at_the_current_rev_and_only_rises():
    revs = [line.rev for line in TASK_MANAGER_GUIDE_CHANGELOG]
    assert revs == sorted(set(revs)) and revs[-1] == TASK_MANAGER_GUIDE_REV


def test_the_guide_file_is_the_one_the_app_installs():
    assert GUIDE_PATH == bundled_install.BUNDLED_ROOT / "huddle" / "SKILL.md"
    assert guide_text() == GUIDE_PATH.read_text(encoding="utf-8")


def test_huddle_guide_description_is_within_the_400_character_budget():
    assert len(mcp.TOOLS["task_manager_guide"].description) <= 400
    assert mcp.TOOLS["task_manager_guide"].gate == "read"


def test_huddle_guide_detail_returns_the_rules_and_the_rev(manager):
    ok, out = call(manager, "task_manager_guide", {"detail": True})
    assert ok, out
    assert out["guide"] == guide_text() and out["guide_rev"] == TASK_MANAGER_GUIDE_REV
    assert "recommend.value" in out["guide"] and "BOOLEAN" in out["guide"]
    assert "changelog" not in out


def test_huddle_guide_since_rev_answers_only_what_changed(manager):
    ok, out = call(manager, "task_manager_guide", {"since_rev": 1})
    assert ok, out
    assert "guide" not in out and [c["rev"] for c in out["changes"]] == [line.rev for line in TASK_MANAGER_GUIDE_CHANGELOG if line.rev > 1 and line.agent_facing]
    assert out["since_rev"] == 1 and out["guide_rev"] == TASK_MANAGER_GUIDE_REV


def test_huddle_guide_since_current_rev_is_up_to_date(manager):
    ok, out = call(manager, "task_manager_guide", {"since_rev": TASK_MANAGER_GUIDE_REV})
    assert ok, out
    assert out["up_to_date"] is True and "guide" not in out and "changes" not in out


def test_huddle_guide_refuses_a_bad_since_rev_and_unknown_arguments(manager):
    for args in ({"since_rev": -1}, {"since_rev": "1"}, {"since_rev": True}, {"nope": 1}):
        ok, out = call(manager, "task_manager_guide", args)
        assert not ok, args


def test_changing_the_rules_requires_bumping_the_rev():
    assert guide_hash(mcp.TOOLS) == TASK_MANAGER_GUIDE_HASH, (
        f"huddle rules changed: bump TASK_MANAGER_GUIDE_REV (now {TASK_MANAGER_GUIDE_REV}), add a TASK_MANAGER_GUIDE_CHANGELOG line and set TASK_MANAGER_GUIDE_HASH to "
        f"{guide_hash(mcp.TOOLS)}")


def test_the_hash_moves_with_the_bundled_skill_text(tmp_path):
    guide = tmp_path / "SKILL.md"
    guide.write_text("a")
    before = guide_hash(mcp.TOOLS, guide)
    guide.write_text("b")
    assert guide_hash(mcp.TOOLS, guide) != before


def test_the_hash_moves_with_a_tool_description():
    import dataclasses

    changed = {**mcp.TOOLS, "task_manager_guide": dataclasses.replace(mcp.TOOLS["task_manager_guide"], description="different")}
    assert guide_hash(changed) != guide_hash(mcp.TOOLS)


def test_the_changelog_has_the_addon_convention_line():
    assert TASK_MANAGER_GUIDE_REV >= 3
    line = {c.rev: c.summary for c in TASK_MANAGER_GUIDE_CHANGELOG}[3]
    assert "extends: huddle" in line and "guide_rev" in line and "stale_extensions" in line
    assert "## 16. Extending the huddle rules" in guide_text() and "extends: huddle" in guide_text()


def test_stale_extensions_is_present_only_when_an_addon_is_behind(manager, monkeypatch):
    from src.cplugs.huddle import mcp as huddle_mcp

    monkeypatch.setattr(huddle_mcp, "stale_extensions", lambda *a, **k: [])
    ok, out = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert ok and "stale_extensions" not in out
    rows = [{"name": "huddle-joe", "written_for": 2, "current": TASK_MANAGER_GUIDE_REV}]
    monkeypatch.setattr(huddle_mcp, "stale_extensions", lambda *a, **k: rows)
    ok, out = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert ok and out["stale_extensions"] == rows
