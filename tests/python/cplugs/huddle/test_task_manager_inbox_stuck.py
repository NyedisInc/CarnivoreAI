
from __future__ import annotations

import asyncio
import time

import pytest

from src.cplugs.huddle import inbox, inbox_delivery, service
from src.cplugs.huddle.roles import ask, lead
from src.cplugs.huddle.roles.store import LeadCannotDnd, RoleStore
from src.cplugs.sdk import session_bring_up
from tests.python.cplugs.huddle.test_task_manager_inbox import BASE, env, queue  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, row  # noqa: F401

PASTE = "backlog dark mode\nnow fix the login bug\n\nask me about the invoice export\n  and the csv one\nlast line"


def late(wait: float = inbox.DEFAULT_FALLBACK_S) -> float:
    return time.time() + wait + 1


def run_pass(env, clock=None) -> int:
    return asyncio.run(inbox_delivery.deliver_pass(env.ctx, clock or time.time))


def stick(client, env, text: str = PASTE) -> dict:
    env.set_rows([])
    entry = queue(client, text)["entry"]
    run_pass(env, lambda: late())
    carriers = env.inbox.carriers(entry["id"])
    return {"entry": entry, "carrier": carriers[0] if carriers else None}


def question_of(env, carrier: int) -> dict:
    return [m for m in env.store.item(carrier)["thread"] if m["kind"] == "question" and not m["answered"]][-1]


def answer(client, env, carrier: int, choice: str) -> dict:
    reply = client.post(f"{BASE}/questions/{question_of(env, carrier)['id']}/answer", json={"answers": {"q1": {"choice": choice}}})
    assert reply.status_code == 200, reply.text
    return reply.json()


def test_a_five_line_paste_is_one_entry_kept_whole_and_told_whole(client, env):
    env.set_rows([row("ses_new", 12, minutes_ago=1)])
    answered = queue(client, PASTE)
    assert [e["text"] for e in client.get(f"{BASE}/inbox").json()["entries"]] == [PASTE]
    run_pass(env)
    assert len(env.pasted) == 1 and "ask me about the invoice export / and the csv one / last line" in env.pasted[0][1]
    assert env.inbox.get(answered["entry"]["id"])["text"] == PASTE


def test_filing_goes_to_the_lead_else_the_most_recently_active_session(client, env):
    env.set_rows([row("ses_old", 12, minutes_ago=30), row("ses_new", 12, minutes_ago=1)])
    queue(client)
    run_pass(env)
    assert [t for t, _ in env.pasted] == ["ses_new"]
    RoleStore(env.store).set_lead("12", "ses_old", lead.BY_OWNER)
    queue(client, "second thing")
    run_pass(env)
    assert [t for t, _ in env.pasted] == ["ses_new", "ses_old"]
    with pytest.raises(LeadCannotDnd):
        RoleStore(env.store).set_dnd("ses_old", True)
    RoleStore(env.store).set_dnd("ses_new", True)
    queue(client, "third thing")
    run_pass(env)
    assert [t for t, _ in env.pasted][-1] == "ses_old"


def test_two_minutes_with_nobody_filing_raises_exactly_one_question_and_keeps_the_entry_queued(client, env):
    env.set_rows([])
    entry = queue(client)["entry"]
    start = time.time()
    assert run_pass(env, lambda: start) == 0 and env.inbox.get(entry["id"])["status"] == "queued"
    assert run_pass(env, lambda: start + inbox.DEFAULT_FALLBACK_S + 1) == 1
    assert run_pass(env, lambda: start + inbox.DEFAULT_FALLBACK_S + 400) == 0
    carriers = env.inbox.carriers(entry["id"])
    assert len(carriers) == 1
    stored = env.inbox.get(entry["id"])
    assert stored["status"] == inbox.STUCK and stored["item_ids"] == []
    message = question_of(env, carriers[0])
    assert (message["author"], message["author_key"], message["category"]) == ("claude", "carnivore", ask.INBOX_STUCK)
    form = client.get(f"{BASE}/questions/{message['id']}").json()
    assert [(o["id"], o["label"]) for o in form["ask"]["questions"][0]["options"]] == [
        ("file", "file it myself"), ("session", "start a session"), ("wait", "wait")]
    assert env.store.item(carriers[0])["state"] == "todo"
    assert [p["status"] for p in client.get(f"{BASE}/lists/12").json()["inbox"]] == ["stuck"]
    assert not env.inbox.has_open()


def test_file_it_myself_files_one_plain_task_linked_to_the_original_and_removes_the_question(client, env):
    stuck = stick(client, env)
    answer(client, env, stuck["carrier"], "file")
    done = env.inbox.get(stuck["entry"]["id"])
    assert done["status"] == inbox.FALLBACK and done["error"] == inbox.REASON_OWNER_FILED and len(done["item_ids"]) == 1
    task = env.store.item(done["item_ids"][0])
    assert task["text"] == PASTE and task["state"] == "open" and task["from_inbox"] == {"id": stuck["entry"]["id"], "text": PASTE, "direct": True}
    assert env.inbox.carriers(stuck["entry"]["id"]) == []
    assert [i["id"] for i in client.get(f"{BASE}/lists/12").json()["items"]] == [task["id"]]


def test_wait_re_arms_the_timer_and_a_second_silence_asks_again(client, env):
    stuck = stick(client, env)
    answer(client, env, stuck["carrier"], "wait")
    again = env.inbox.get(stuck["entry"]["id"])
    assert again["status"] == inbox.QUEUED and env.inbox.carriers(again["id"]) == []
    assert run_pass(env) == 0 and env.inbox.carriers(again["id"]) == []
    assert run_pass(env, lambda: late()) == 1
    assert len(env.inbox.carriers(again["id"])) == 1 and env.inbox.get(again["id"])["status"] == inbox.STUCK


def test_start_a_session_starts_one_and_offers_the_entry_to_it(client, env, monkeypatch):
    stuck = stick(client, env)
    started = []

    async def start(ops, project_id):
        started.append(project_id)
        env.set_rows([row("ses_fresh", 12, minutes_ago=0)])
        return "ses_fresh"

    monkeypatch.setattr(session_bring_up, "wake_newest_or_start", start)
    answer(client, env, stuck["carrier"], "session")
    assert started == [12]
    assert [t for t, _ in env.pasted] == ["ses_fresh"] and "file entry" in env.pasted[0][1]
    after = env.inbox.get(stuck["entry"]["id"])
    assert after["status"] == inbox.FILING and after["delivered_to"] == "ses_fresh" and env.inbox.carriers(after["id"]) == []


def test_a_session_that_cannot_start_leaves_the_entry_waiting_not_lost(client, env, monkeypatch):
    stuck = stick(client, env)

    async def fail(ops, project_id):
        raise session_bring_up.BringUpFailed("no")

    monkeypatch.setattr(session_bring_up, "wake_newest_or_start", fail)
    answer(client, env, stuck["carrier"], "session")
    assert env.inbox.get(stuck["entry"]["id"])["status"] == inbox.QUEUED and env.pasted == []


def test_a_late_session_filing_a_stuck_entry_withdraws_the_question(client, env):
    stuck = stick(client, env)
    filed = client.post(f"{BASE}/inbox/{stuck['entry']['id']}/file", json={"items": [{"title": "dark mode", "text": "dark mode"}]})
    assert filed.status_code == 200
    assert env.inbox.carriers(stuck["entry"]["id"]) == [] and env.inbox.get(stuck["entry"]["id"])["status"] == inbox.FILED


def test_every_task_filed_from_one_entry_links_the_one_original_and_a_delete_keeps_it(client, env):
    entry = queue(client)["entry"]
    filed = client.post(f"{BASE}/inbox/{entry['id']}/file", json={"items": [{"title": "a", "text": "a"}, {"title": "b", "text": "b"}]}).json()
    first, second = filed["items"]
    assert first["from_inbox"]["id"] == second["from_inbox"]["id"] == entry["id"] and first["from_inbox"]["text"] == entry["text"]
    env.store.delete(first["id"], actor="joe")
    assert env.store.item(second["id"])["from_inbox"] == {"id": entry["id"], "text": entry["text"], "direct": True}
    assert client.get(f"{BASE}/inbox/{entry['id']}").json()["text"] == entry["text"]
