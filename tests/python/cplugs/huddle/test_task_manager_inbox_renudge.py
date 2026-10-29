
from __future__ import annotations

from src.cplugs.huddle import inbox
from tests.python.cplugs.huddle.test_task_manager_inbox import BASE, env, queue, row  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_inbox_promoted import promote
from tests.python.cplugs.huddle.test_task_manager_inbox_stuck import app, client, run_pass, stick  # noqa: F401


def test_the_next_send_tells_every_stuck_entry_once_oldest_first_and_withdraws_their_questions(client, env):
    first, second = stick(client, env, "backlog one"), stick(client, env, "backlog two")
    env.set_rows([row("ses_new", 12, minutes_ago=1)])
    fresh = queue(client, "backlog three")["entry"]
    for stuck in (first, second):
        assert env.inbox.get(stuck["entry"]["id"])["status"] == inbox.QUEUED and env.inbox.carriers(stuck["entry"]["id"]) == []
    run_pass(env)
    told = [text for _target, text in env.pasted]
    assert len(told) == 3 and "backlog one" in told[0] and "backlog two" in told[1] and "backlog three" in told[2]
    assert all(env.inbox.get(e["entry"]["id"] if "entry" in e else e["id"])["status"] == inbox.FILING for e in (first, second, {"id": fresh["id"]}))
    run_pass(env)
    assert len(env.pasted) == 3


def test_a_filed_entry_is_never_re_sent_and_another_projects_stuck_entry_is_left_alone(client, env):
    stuck, other = stick(client, env, "backlog one"), stick(client, env, "elsewhere")
    client.post(f"{BASE}/inbox/{stuck['entry']['id']}/file", json={"items": [{"title": "one", "text": "one"}]})
    with env.store._connect(True) as conn:
        conn.execute("UPDATE work_inbox SET list_key = '13' WHERE id = ?", (other["entry"]["id"],))
    env.set_rows([row("ses_new", 12, minutes_ago=1)])
    queue(client, "new thing")
    assert env.inbox.get(stuck["entry"]["id"])["status"] == inbox.FILED
    assert env.inbox.get(other["entry"]["id"])["status"] == inbox.STUCK
    run_pass(env)
    assert len(env.pasted) == 1 and "new thing" in env.pasted[0][1]


def test_a_stuck_entry_whose_carrier_was_worked_on_is_adopted_and_not_re_sent(client, env):
    stuck = stick(client, env, "backlog one")
    promote(env.store, stuck["carrier"])
    env.set_rows([row("ses_new", 12, minutes_ago=1)])
    queue(client, "new thing")
    entry = env.inbox.get(stuck["entry"]["id"])
    assert entry["status"] == inbox.FILED and entry["item_ids"] == [stuck["carrier"]]
    run_pass(env)
    assert len(env.pasted) == 1


def test_the_nudge_route_re_sends_one_stuck_entry_right_away(client, env):
    one, two = stick(client, env, "backlog one"), stick(client, env, "backlog two")
    env.set_rows([row("ses_new", 12, minutes_ago=1)])
    answer = client.post(f"{BASE}/inbox/{one['entry']['id']}/nudge")
    assert answer.status_code == 200 and answer.json()["sent"] is True
    assert answer.json()["entry"]["status"] == inbox.FILING and answer.json()["entry"]["delivered_to"] == "ses_new"
    assert len(env.pasted) == 1 and "backlog one" in env.pasted[0][1]
    assert env.inbox.carriers(one["entry"]["id"]) == []
    assert env.inbox.get(two["entry"]["id"])["status"] == inbox.STUCK


def test_the_nudge_with_no_session_keeps_the_entry_waiting_not_lost(client, env):
    stuck = stick(client, env)
    env.set_rows([])
    answer = client.post(f"{BASE}/inbox/{stuck['entry']['id']}/nudge").json()
    assert answer["sent"] is False and answer["entry"]["status"] == inbox.QUEUED and env.pasted == []


def test_the_nudge_refuses_an_entry_that_is_not_stuck(client, env):
    stuck = stick(client, env)
    client.post(f"{BASE}/inbox/{stuck['entry']['id']}/file", json={"items": [{"title": "x", "text": "x"}]})
    assert client.post(f"{BASE}/inbox/{stuck['entry']['id']}/nudge").status_code == 400
    waiting = queue(client, "still waiting")["entry"]
    assert client.post(f"{BASE}/inbox/{waiting['id']}/nudge").status_code == 400
    assert client.post(f"{BASE}/inbox/99999/nudge").status_code == 404
