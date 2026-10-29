
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import board_port, reply as task_manager_reply, send_queue
from src.cplugs.reviewboard import scan
from tests.python.cplugs.reviewboard.harness import BASE, Env, task_manager_on, task_manager_store, make_env
from tests.python.cplugs.reviewboard.test_publish import create_body


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    env = make_env(tmp_path)
    ctx = task_manager_on(env, monkeypatch)
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as client:
        yield env, client, ctx
    board_port.unregister()


@pytest.fixture
def board(world):
    env, client, _ctx = world
    item = task_manager_store(env).add("all", "redo the bottom bar", actor="claude", title="Part 3 bottom bar")["id"]
    r = client.post(f"{BASE}/boards", json=create_body(item))
    assert r.status_code == 200, r.text
    return r.json()["slug"], item


def round_body(**over):
    return {"client_round_id": str(uuid.uuid4()), "revision": "r1",
            "answers": [{"prompt": "layout", "options": ["b"]}, {"prompt": "padding", "checked": True}],
            "anchor_notes": [{"anchor": "send", "text": "too close to the edge"}], "note": "closer, keep going",
            "context": {"width": 412, "fit": "actual"}, **over}


def thread(env: Env, item: int) -> list:
    return [m for m in task_manager_store(env).item(item)["thread"] if m.get("category") != "status"]


def sidecar(env: Env, slug: str) -> dict:
    return json.loads((env.board(slug) / "sidecar.json").read_text())


def test_a_round_lands_as_joes_reply_through_the_reply_boxs_function(world, board, monkeypatch):
    env, client, _ = world
    slug, item = board
    calls = []
    real = task_manager_reply.post_reply

    async def spy(*args, **kwargs):
        calls.append((args[1], kwargs.get("parts")))
        return await real(*args, **kwargs)

    monkeypatch.setattr(task_manager_reply, "post_reply", spy)
    r = client.post(f"{BASE}/boards/{slug}/rounds", json=round_body())
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["delivery"]["state"] == "posted" and out["duplicate"] is False and out["round"]["id"] == "n1"
    assert [c[0] for c in calls] == [item] and "board_round" in calls[0][1]
    message = thread(env, item)[-1]
    assert message["author"] == "joe" and message["kind"] == "reply"
    assert message["board_round"] == {"slug": slug, "round": "n1", "revision": "r1"}
    assert message["text"].startswith("review round 1 on r1 (bottom bar)")
    assert "which button row: two rows" in message["text"] and "send button: too close to the edge" in message["text"]
    assert f'task_manager_board_get {{"board": "{slug}", "since_round": 0}}' in message["text"]
    assert out["delivery"]["message_id"] == message["id"]
    assert scan.scan(env.root).exit_code == 0
    assert out["state"] == "with_claude"


def test_the_same_client_round_id_twice_lands_once(world, board):
    env, client, _ = world
    slug, item = board
    body = round_body()
    first = client.post(f"{BASE}/boards/{slug}/rounds", json=body).json()
    before = (env.board(slug) / "sidecar.json").read_bytes()
    count = len(thread(env, item))
    second = client.post(f"{BASE}/boards/{slug}/rounds", json=body).json()
    assert second["duplicate"] is True and second["round"] == first["round"] and second["delivery"] == first["delivery"]
    assert (env.board(slug) / "sidecar.json").read_bytes() == before
    assert len(thread(env, item)) == count and len(sidecar(env, slug)["rounds"]) == 1


def test_a_round_queues_its_tell_on_the_server(world, board):
    env, client, ctx = world
    slug, item = board
    send_queue.use_clock(lambda: 1000.0)
    try:
        out = client.post(f"{BASE}/boards/{slug}/rounds", json=round_body()).json()
        assert out["delivery"]["state"] == "posted" and out["tell"] == "queued"
        assert "all" in send_queue.state(ctx)["lists"]
        assert "tell" not in sidecar(env, slug)["rounds"][0]["delivery"]
        send_queue.use_clock(lambda: 1000.0)
        board_port.unregister()
        late = client.post(f"{BASE}/boards/{slug}/rounds", json=round_body()).json()
        assert late["delivery"]["state"] == "undelivered" and late["tell"] is None
        assert send_queue.state(ctx)["lists"] == {}
        board_port.register(ctx)
        again = client.post(f"{BASE}/boards/{slug}/rounds/n2/resend", json={}).json()
        assert again["delivery"]["state"] == "posted" and again["tell"] == "queued"
        assert "all" in send_queue.state(ctx)["lists"]
    finally:
        send_queue.reset()


def test_a_failed_delivery_keeps_the_round_and_resend_posts_it_once(world, board):
    env, client, ctx = world
    slug, item = board
    board_port.unregister()
    out = client.post(f"{BASE}/boards/{slug}/rounds", json=round_body()).json()
    assert out["delivery"]["state"] == "undelivered" and "task manager" in out["delivery"]["reason"] and out["state"] == "undelivered"
    assert sidecar(env, slug)["rounds"][0]["delivery"]["state"] == "undelivered"
    count = len(thread(env, item))
    board_port.register(ctx)
    again = client.post(f"{BASE}/boards/{slug}/rounds/n1/resend", json={}).json()
    assert again["delivery"]["state"] == "posted" and again["duplicate"] is False
    assert len(thread(env, item)) == count + 1
    third = client.post(f"{BASE}/boards/{slug}/rounds/n1/resend", json={}).json()
    assert third["duplicate"] is True and len(thread(env, item)) == count + 1
    assert client.post(f"{BASE}/boards/{slug}/rounds/n9/resend", json={}).status_code == 404


def test_a_round_that_does_not_fit_the_revision_is_refused_and_writes_nothing(world, board):
    env, client, _ = world
    slug, item = board
    before = (env.board(slug) / "sidecar.json").read_bytes()
    for over in ({"answers": [{"prompt": "layout", "options": ["zzz"]}]}, {"answers": [{"prompt": "nope", "checked": True}]},
                 {"anchor_notes": [{"anchor": "nope", "text": "x"}]}, {"revision": "r9"}):
        assert client.post(f"{BASE}/boards/{slug}/rounds", json=round_body(**over)).status_code == 422, over
    assert (env.board(slug) / "sidecar.json").read_bytes() == before and len(thread(env, item)) == 1


def test_unanswered_prompts_are_recorded_and_a_send_clears_its_draft(world, board):
    env, client, _ = world
    slug, _item = board
    d = {"rev": 0, "revision": "r1", "answers": [], "anchor_notes": [], "note": "half", "client_round_id": (cid := str(uuid.uuid4()))}
    assert client.put(f"{BASE}/boards/{slug}/draft", json=d).status_code == 200
    out = client.post(f"{BASE}/boards/{slug}/rounds", json=round_body(client_round_id=cid, answers=[{"prompt": "layout", "options": ["a"]}])).json()
    assert out["round"]["unanswered"] == ["padding"]
    assert client.get(f"{BASE}/boards/{slug}/draft").json() == {"draft": None}
    assert env.published.count("cplug.reviewboard.drafts") == 2 and "cplug.reviewboard.boards" in env.published


def test_drafts_are_kept_on_the_server_and_a_stale_write_is_refused(world, board):
    env, client, _ = world
    slug, _item = board
    d = {"rev": 0, "revision": "r1", "answers": [{"prompt": "padding", "checked": True}], "anchor_notes": [], "note": "", "client_round_id": str(uuid.uuid4())}
    saved = client.put(f"{BASE}/boards/{slug}/draft", json=d).json()["draft"]
    assert saved["rev"] == 1 and client.get(f"{BASE}/boards/{slug}/draft").json()["draft"]["answers"][0]["checked"] is True
    stale = client.put(f"{BASE}/boards/{slug}/draft", json={**d, "note": "other device"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "reviewboard_draft_stale" and stale.json()["detail"]["draft"]["rev"] == 1
    assert client.put(f"{BASE}/boards/{slug}/draft", json={**d, "rev": 1, "note": "next"}).json()["draft"]["rev"] == 2
    assert not any((env.board(slug)).glob("*draft*"))
    assert client.delete(f"{BASE}/boards/{slug}/draft").status_code == 204
    assert client.get(f"{BASE}/boards/{slug}/draft").json() == {"draft": None}
    assert client.get(f"{BASE}/boards/not-a-slug/draft").status_code == 404


def test_relink_moves_later_rounds_and_keeps_the_old_link(world, board):
    env, client, _ = world
    slug, item = board
    other = task_manager_store(env).add("all", "another task", actor="claude", title="Other")["id"]
    out = client.patch(f"{BASE}/boards/{slug}/task", json={"item_id": other})
    assert out.status_code == 200 and out.json()["task"]["item_id"] == other
    history = sidecar(env, slug)["task"]["history"]
    assert history[-1]["item_id"] == other and history[-1]["from"] == item and history[-1]["by"] == "joe"
    sent = client.post(f"{BASE}/boards/{slug}/rounds", json=round_body()).json()
    assert sent["delivery"]["item_id"] == other and thread(env, other)[-1]["author"] == "joe"
    assert client.patch(f"{BASE}/boards/{slug}/task", json={"item_id": 99999}).json()["detail"]["code"] == "reviewboard_no_task"


def test_a_board_with_no_task_refuses_a_send(world, board):
    env, client, _ = world
    slug, _ = board
    path = env.board(slug) / "sidecar.json"
    doc = json.loads(path.read_text())
    doc["task"] = None
    path.write_text(json.dumps(doc, indent=2) + "\n")
    r = client.post(f"{BASE}/boards/{slug}/rounds", json=round_body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_unlinked"


def test_a_round_on_a_review_task_reopens_it_with_the_joe_replied_lineage_row(world, board):
    from contextlib import closing

    from src.cplugs.huddle import lineage

    env, client, _ = world
    slug, item = board
    store = task_manager_store(env)
    assert store.item(item)["state"] == "review"
    r = client.post(f"{BASE}/boards/{slug}/rounds", json=round_body())
    assert r.status_code == 200, r.text
    assert r.json()["delivery"]["state"] == "posted"
    assert store.item(item)["state"] == "open"
    with closing(store._connect(False)) as conn:
        rows = [(x["from"], x["to"], x["by"], x["detail"]) for x in lineage.for_item(conn, item)]
    assert rows[-1] == ("review", "open", "owner", "joe replied")
