
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.core.work.storage import WorkStorage
from src.plugins.taskmanager import answers, artifacts, progress, rich_ask, rules
from src.plugins.taskmanager.cards import driven
from src.plugins.taskmanager.answer_writer import AnswerWriter
from src.plugins.taskmanager.rules import CLAUDE, JOE
from src.plugins.taskmanager.store import TaskManagerStore
from src.plugins.sdk.cards import CardRefused
from src.plugins.sdk.owner_text import raw_cap
from tests.python.cplugs.taskmanager.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.test_owner_text import CLEAN_LOG, COLORED_LOG, REFUSED, STRIPPED

BASE = "/api/v1/cplugs/huddle"
BAD = sorted(REFUSED)


@pytest.fixture()
def store(tmp_path: Path) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path / "huddle"), notify=lambda key: None)


def raw_write(store: TaskManagerStore, query: str, *args: object) -> None:
    with closing(store._connect(True)) as conn, conn:
        conn.execute(query, args)


@pytest.mark.parametrize("name", BAD)
def test_clean_text_refuses_what_is_never_typed_by_accident(name: str) -> None:
    with pytest.raises(rules.TaskManagerInvalid, match="text may not contain hidden or control characters"):
        rules.clean_text(f"ship{REFUSED[name]}", "text", rules.MAX_MESSAGE)


@pytest.mark.parametrize("name", sorted(STRIPPED))
def test_clean_text_removes_a_pastes_accidents(name: str) -> None:
    assert rules.clean_text(f"ship{STRIPPED[name]} it", "text", rules.MAX_MESSAGE) == "ship it"


@pytest.mark.parametrize("name", BAD)
def test_reply_and_add_routes_refuse_hidden_text(client, name: str) -> None:  # noqa: F811
    item = client.post(f"{BASE}/lists/12/items", json={"text": "check the build"}).json()["id"]
    bad = f"yes{REFUSED[name]}"
    assert client.post(f"{BASE}/items/{item}/messages", json={"text": bad}).status_code == 400
    assert client.post(f"{BASE}/lists/12/items", json={"text": bad}).status_code == 400
    assert not [m for m in client.get(f"{BASE}/items/{item}").json()["thread"] if m["author"] == "joe"]


def test_a_pasted_colored_log_comes_through_clean(client) -> None:  # noqa: F811
    item = client.post(f"{BASE}/lists/12/items", json={"text": "check the build"}).json()["id"]
    tail = "\n" + "\n".join(f"\tat frame {n}" for n in range(120)) + "\n\n\n\n```\nok\n```\u00a0end"
    r = client.post(f"{BASE}/items/{item}/messages", json={"text": COLORED_LOG + tail})
    assert r.status_code == 200, r.text
    assert r.json()["message"]["text"] == CLEAN_LOG + tail.replace("\u00a0", " ")


@pytest.mark.parametrize("name", BAD)
def test_agent_text_on_the_owners_screen_is_checked(name: str) -> None:
    hidden = REFUSED[name]
    for title, description in ((f"t{hidden}", ""), ("t", f"d{hidden}")):
        with pytest.raises(rules.TaskManagerInvalid, match="hidden or control"):
            artifacts.clean(title, description, "<p>x</p>")
    for note, worker in ((f"n{hidden}", None), (None, f"w{hidden}")):
        with pytest.raises(rules.TaskManagerInvalid, match="hidden or control"):
            progress.clean("testing", note, worker)
    for question in ({"prompt": f"p{hidden}", "type": "yes_no"},
                     {"prompt": "run it", "type": "single", "options": [{"id": "a", "label": "ran"}, {"id": "b", "label": "failed"}], "command": {"text": f"ls{hidden}\necho"}}):
        with pytest.raises(rules.TaskManagerInvalid, match="hidden or control"):
            rich_ask.normalize([question])
    question = {"id": "q1", "type": "single", "prompt": "pick", "options": [{"id": "a", "label": "a"}], "other": True}
    with pytest.raises(rules.TaskManagerInvalid, match="hidden or control"):
        answers.validate([question], {"q1": {"other": f"mine{hidden}"}})


def test_a_command_is_judged_before_it_is_split_and_parts_match_the_text() -> None:
    single = {"prompt": "run it", "type": "single", "options": [{"id": "a", "label": "ran"}, {"id": "b", "label": "failed"}]}
    for sep in ("\u2028", "\x1c", "\x0b", "\x0c"):
        with pytest.raises(rules.TaskManagerInvalid, match="hidden or control"):
            rich_ask.normalize([{**single, "command": {"text": f"ls{sep}rm -rf x"}}])
    normalized, _typed = rich_ask.normalize([{**single, "command": {"text": "ls\r\necho \x1b[32mok\x1b[0m"}}])
    assert normalized[0]["command"]["text"] == "ls\necho ok"
    assert "   ls\n   echo ok" in rich_ask.flatten("", normalized)


def test_a_cleaned_artifact_and_progress_keep_their_text(tmp_path: Path) -> None:
    assert artifacts.clean("Lay\u200bout\u00a0A", "two\x7f columns", "<p>\u200b</p>")[:2] == ("Layout A", "two columns")
    assert progress.clean("testing", "12\u00ad of 40", "wor\x85ker") == {"phase": "testing", "note": "12 of 40", "worker": "worker"}


def test_a_fork_copies_its_stored_parent_text_cleaned_never_refused(store: TaskManagerStore) -> None:
    parent = store.add("12", "fix the bar", actor=JOE, title="Bar")["id"]
    raw_write(store, "UPDATE work_items SET text = ?, title = ? WHERE id = ?", "fix\u202e the\u200b bar", "B\U000e0041ar", parent)
    fork = store.fork(parent, actor=CLAUDE)["fork"]
    assert (fork["text"], fork["title"]) == ("fix the bar", "Bar")
    with pytest.raises(rules.TaskManagerInvalid, match="hidden or control"):
        store.fork(parent, actor=CLAUDE, text="new\u202e")


def test_an_answer_to_a_stored_prompt_with_a_now_refused_character_still_lands(store: TaskManagerStore) -> None:
    item = store.add("12", "held work", actor=JOE)["id"]
    parts = rich_ask.dump("", [{"id": "q1", "type": "long_text", "prompt": "which\u202e way?", "required": False}])
    question = store.post(item, "which way?", actor=CLAUDE, kind="question", parts=parts)["message"]["id"]
    out = AnswerWriter(store).submit(question, {})
    assert "\u202e" not in out["message"]["text"] and "which way?" in out["message"]["text"]


def test_text_past_the_raw_cap_is_refused_unread() -> None:
    with pytest.raises(rules.TaskManagerInvalid, match="over the 4000 character limit"):
        rules.clean_text("\x9d" * (raw_cap(4000) + 1), "text", 4000)
    assert rules.clean_text("\x1b[31m" * 1000 + "ok", "text", 4000) == "ok"


def test_a_swarm_finish_result_is_cleaned_before_it_is_stored(store: TaskManagerStore) -> None:
    item = store.add("12", "held work", actor=JOE)["id"]
    raw_write(store, "UPDATE work_items SET card_holder = 4, card_held_since = 5.0 WHERE id = ?", item)
    with pytest.raises(CardRefused, match="result may not contain hidden or control characters"):
        driven.finish(store, item, {"result": "done\u202e", "how_to_validate": "run it"}, "agent:4")
    driven.finish(store, item, {"result": "\x1b[32mdone\x1b[0m\r\nall green\u200b", "how_to_validate": "run it"}, "agent:4")
    with closing(store._connect(False)) as conn:
        assert conn.execute("SELECT card_result FROM work_items WHERE id = ?", (item,)).fetchone()[0] == "done\nall green"
