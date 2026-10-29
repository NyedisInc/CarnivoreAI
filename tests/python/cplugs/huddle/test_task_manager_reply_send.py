
from __future__ import annotations

from src.cplugs.huddle import reply_send, service
from src.cplugs.huddle.rules import CLAUDE, JOE, REPLY
from src.cplugs.host import runtime
from src.cplugs.huddle.store import TaskManagerStore
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401

SEND = "/api/v1/cplugs/huddle/lists/12/send"


def test_sentence_names_task_and_message_and_caps_the_list():
    assert reply_send.sentence([]) == ""
    one = reply_send.sentence([(526, 4411)])
    assert "replied in the thread of task 526 (message 4411)" in one and "task_manager_tasks_list item=" in one and "\n" not in one
    many = reply_send.sentence([(i, i * 10) for i in range(1, 8)])
    assert "task 5 (message 50)" in many and "task 6" not in many and "and 2 more" in many


def test_tell_text_appends_the_reply_words_after_the_list_line():
    text = service.send_text("12", "carnivore", 4, replies=[(7, 31)])
    assert text.startswith("the swarm list for carnivore changed: read it") and "(list 12, since 4) and answer there." in text
    assert text.endswith("task 7 (message 31): read a thread with task_manager_tasks_list item=<task id>.")
    assert service.send_text("12", "carnivore", 4) == service.send_text("12", "carnivore", 4, replies=[])


def test_a_tell_after_joes_reply_names_that_task_and_message_only(client, app, pasted):
    store = TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)
    quiet = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "no reply here"}).json()["id"]
    item = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "moved files"}).json()["id"]
    reply = client.post(f"/api/v1/cplugs/huddle/items/{item}/messages", json={"text": "keep them a week"}).json()
    message_id = reply["message"]["id"]
    text = client.post(SEND, json={"target": "ses_old"}).json()["text"]
    assert f"task {item} (message {message_id})" in text and f"task {quiet}" not in text
    store.note_read("ses_old", "12", store.list_heads()["12"])
    client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "later item"})
    assert "replied in the thread" not in client.post(SEND, json={"target": "ses_old"}).json()["text"]


def test_an_agent_message_is_not_an_owner_reply(client, app):
    st = TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)
    item = st.add("12", "x", actor=JOE)["id"]
    st.post(item, "from the agent", actor=CLAUDE)
    assert st.owner_replies("12", 0) == []
    posted = st.post(item, "from joe", actor=JOE, kind=REPLY)
    assert st.owner_replies("12", 0) == [(item, posted["message"]["id"])]
    assert st.owner_replies("12", 0, items=[item + 1]) == []
