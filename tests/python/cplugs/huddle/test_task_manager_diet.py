
from __future__ import annotations

import json

from src.cplugs.huddle import guide_rev, guide_sections, mcp
from src.cplugs.huddle.guide_rev import TASK_MANAGER_GUIDE_CHANGELOG, TASK_MANAGER_GUIDE_REV, guide_text
from src.cplugs.huddle.lean_read import ITEM_THREAD_TAIL
from src.core.mcp import instructions
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401

DEFAULT_GUIDE_MAX_CHARS = 12_000
FULL_GUIDE_MAX_CHARS = 58_000
UP_TO_DATE_MAX_CHARS = 100
CORE_SECTIONS = {1, 2, 3, 4, 5, 6, 7, 12, 15, 32}


OTHER_PANE = AgentCaller("ses_2", "cloude_b", "ses_2")


def chars(out) -> int:
    return len(json.dumps(out))


def test_the_default_answer_is_the_core_plus_an_index_and_no_changelog(manager):
    ok, out = call(manager, "task_manager_guide", {})
    assert ok, out
    assert "changelog" not in out and out["guide_rev"] == TASK_MANAGER_GUIDE_REV
    assert len(out["guide"]) <= DEFAULT_GUIDE_MAX_CHARS and chars(out) <= DEFAULT_GUIDE_MAX_CHARS
    sections = guide_sections.parse(guide_text())[1]
    assert {s.number for s in sections if s.core} == CORE_SECTIONS
    for section in sections:
        assert (f"## {section.number}. " in out["guide"]) == section.core, section.title
    assert "task_manager_guide topic:" in out["guide"] and "detail: true" in out["guide"]
    assert "recommend.value" in out["guide"] and "BOOLEAN" in out["guide"]
    assert guide_sections.CORE_MARKER not in out["guide"]


def test_detail_true_answers_the_whole_guide_and_still_no_changelog(manager):
    ok, out = call(manager, "task_manager_guide", {"detail": True})
    assert ok, out
    assert out["guide"] == guide_text() and "changelog" not in out
    assert len(out["guide"]) <= FULL_GUIDE_MAX_CHARS


def test_topic_returns_one_section_by_number_or_name(manager):
    ok, by_number = call(manager, "task_manager_guide", {"topic": 31})
    assert ok and by_number["guide"].startswith("## 31. Waiting") and by_number["guide"].count("\n## ") == 0
    ok, by_name = call(manager, "task_manager_guide", {"topic": "waiting"})
    assert ok and by_name["guide"] == by_number["guide"] and by_name["topic"].startswith("31. Waiting")
    ok, digits = call(manager, "task_manager_guide", {"topic": "14"})
    assert ok and digits["guide"].startswith("## 14. Tool reference")


def test_a_bad_topic_or_two_selectors_are_refused_with_the_choices(manager):
    ok, text = call(manager, "task_manager_guide", {"topic": 99})
    assert not ok and "no section 99" in text
    ok, text = call(manager, "task_manager_guide", {"topic": "re"})
    assert not ok and "several sections" in text
    ok, text = call(manager, "task_manager_guide", {"topic": 5, "detail": True})
    assert not ok and "only one of" in text


def test_since_the_current_rev_is_up_to_date_in_under_100_characters(manager):
    ok, out = call(manager, "task_manager_guide", {"since_rev": TASK_MANAGER_GUIDE_REV})
    assert ok and out["up_to_date"] is True and chars(out) < UP_TO_DATE_MAX_CHARS


def test_a_bump_that_is_not_agent_facing_keeps_up_to_date(monkeypatch):
    quiet = guide_rev.Change(TASK_MANAGER_GUIDE_REV + 1, "HTTP only.", agent_facing=False)
    monkeypatch.setattr(guide_rev, "TASK_MANAGER_GUIDE_CHANGELOG", (*TASK_MANAGER_GUIDE_CHANGELOG, quiet))
    assert guide_rev.guide_answer(TASK_MANAGER_GUIDE_REV) == {"up_to_date": True, "since_rev": TASK_MANAGER_GUIDE_REV}
    loud = guide_rev.Change(TASK_MANAGER_GUIDE_REV + 2, "A tool changed.")
    monkeypatch.setattr(guide_rev, "TASK_MANAGER_GUIDE_CHANGELOG", (*TASK_MANAGER_GUIDE_CHANGELOG, quiet, loud))
    out = guide_rev.guide_answer(TASK_MANAGER_GUIDE_REV)
    assert [c["rev"] for c in out["changes"]] == [TASK_MANAGER_GUIDE_REV + 2]


def test_since_rev_lists_only_agent_facing_lines():
    out = guide_rev.guide_answer(1)
    quiet = {line.rev for line in TASK_MANAGER_GUIDE_CHANGELOG if not line.agent_facing}
    assert quiet and not quiet & {c["rev"] for c in out["changes"]}
    assert 74 in {c["rev"] for c in out["changes"]}


def test_every_changelog_line_that_says_no_change_for_agents_is_marked():
    for line in TASK_MANAGER_GUIDE_CHANGELOG:
        lead = line.summary.lower()
        if lead.startswith(("http only", "http and ui only")):
            assert not line.agent_facing, line.rev


def test_the_hash_does_not_cover_the_human_doc():
    import inspect

    assert "doc_path" not in inspect.signature(guide_rev.guide_hash).parameters


def _three_long_threads(manager):
    store = huddle_store(manager)
    ids = []
    for n in range(3):
        item = store.add("all", f"task {n}", actor="joe")["id"]
        for k in range(15):
            store.post(item, f"message {k} " + "context " * 40, actor="joe")
        ids.append(item)
    cursor = store.current_cursor()
    for item in ids:
        store.post(item, "the new message " + "x" * 80, actor="joe")
    return store, cursor, ids


def test_changes_default_sends_no_thread_and_is_under_40_percent_of_detail(manager):
    _store, cursor, ids = _three_long_threads(manager)
    ok, lean = call(manager, "task_manager_changes", {"since": cursor, "list": "all"})
    assert ok and [m["item"] for m in lean["messages"]] == ids
    assert all("thread" not in i for i in lean["items"])
    ok, full = call(manager, "task_manager_changes", {"since": cursor, "list": "all", "detail": True}, caller=OTHER_PANE)
    assert ok and all(len(i["thread"]) == 16 for i in full["items"])
    assert full["messages"] == lean["messages"]
    assert chars(lean) < 0.4 * chars(full), (chars(lean), chars(full))


def test_an_explicit_include_thread_still_works_for_a_cached_schema(manager):
    _store, cursor, _ids = _three_long_threads(manager)
    ok, out = call(manager, "task_manager_changes", {"since": cursor, "list": "all", "include_thread": True}, caller=OTHER_PANE)
    assert ok and all("thread" in i for i in out["items"])


def test_item_read_sends_the_last_10_messages_and_thread_more(manager):
    _store, _cursor, ids = _three_long_threads(manager)
    ok, out = call(manager, "task_manager_tasks_list", {"item": ids[0]})
    assert ok
    thread = out["item"]["thread"]
    assert len(thread) == ITEM_THREAD_TAIL == 10 and out["item"]["thread_more"] == 6
    assert thread[-1]["text"].startswith("the new message")
    ok, whole = call(manager, "task_manager_tasks_list", {"item": ids[0], "detail": True})
    assert ok and len(whole["item"]["thread"]) == 16 and "thread_more" not in whole["item"]
    assert whole["item"]["thread"][-10:] == thread


def test_a_short_thread_has_no_thread_more(manager):
    store = huddle_store(manager)
    item = store.add("all", "short", actor="joe")["id"]
    store.post(item, "one", actor="joe")
    ok, out = call(manager, "task_manager_tasks_list", {"item": item})
    assert ok and len(out["item"]["thread"]) == 1 and "thread_more" not in out["item"]


def test_the_huddle_instruction_line_fits_every_variant_and_says_progress_and_reply_skip_the_guide():
    for channel in (False, True):
        text = instructions.guide(None, channel=channel)
        assert len(text) <= instructions.MAX_CHARS == 1800
    text = instructions.guide(None, channel=True)
    line = next(ln for ln in text.splitlines() if ln.startswith("- huddle:"))
    assert "task_manager_progress_set" in line and "task_manager_reply" in line and "guide_rev rises" in line
    assert "task_manager_progress_set and task_manager_reply" in mcp.TOOLS["task_manager_guide"].description


def test_core_stays_core_when_the_file_changes_a_section():
    text = "---\nname: x\n---\n\n# t\n\n## 1. A\n<!-- core -->\nbody\n\n## 2. B (guide rev 3)\nrest\n"
    core = guide_sections.core_text(text)
    assert "## 1. A" in core and "body" in core and "rest" not in core and "2 B" in core and "guide rev" not in core
