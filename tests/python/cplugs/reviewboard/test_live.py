
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import board_port
from types import SimpleNamespace

from src.cplugs.reviewboard import document, scan, viewer
from src.cplugs.sdk import signed_links
from src.cplugs.reviewboard.errors import BoardNotFound
from tests.python.cplugs.reviewboard.boards import SIDECAR, make_board, make_root, sidecar as v1_sidecar
from tests.python.cplugs.reviewboard.harness import BASE, Env, task_manager_on, task_manager_store, make_env
from tests.python.cplugs.reviewboard.test_publish import ANCHORS, HTML, PROMPTS, create_body, tree

PAGE_A = "<!doctype html><title>demo</title><div data-rb-anchor='send'>send A</div>"
PAGE_B = "<!doctype html><title>demo</title><div data-rb-anchor='send'>send B</div>"


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> Env:
    made = make_env(tmp_path)
    task_manager_on(made, monkeypatch)
    yield made
    board_port.unregister()


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def signing(monkeypatch) -> None:
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))


@pytest.fixture
def item(env: Env) -> int:
    return task_manager_store(env).add("all", "demo the bottom bar", actor="claude", title="demo")["id"]


@pytest.fixture
def told(monkeypatch) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    async def tell_session(self, session_id: str, text: str) -> Dict[str, Any]:
        calls.append({"session": session_id, "text": text})
        return {"told": True, "via": "channel"}

    monkeypatch.setattr(board_port.BoardPort, "tell_session", tell_session)
    return calls


def draft_body(**over: Any) -> Dict[str, Any]:
    return {"summary": "first look", "html": PAGE_A, "viewport": 320, "prompts": PROMPTS, "anchors": ANCHORS, **over}


def start(client, item: int, **over: Any) -> Dict[str, Any]:
    r = client.post(f"{BASE}/boards/live", json={"slug_name": "demo", "title": "demo", "task": {"item_id": item}, **draft_body(), **over})
    assert r.status_code == 200, r.text
    return r.json()


def start_as_agent(env: Env, item: int, **over: Any) -> str:
    ok, out = env.call("task_manager_board_live_set", {"name": "demo", "title": "demo", "task": item, **draft_body(), **over})
    assert ok, out
    return out["slug"]


def side(env: Env, slug: str) -> Dict[str, Any]:
    return json.loads((env.board(slug) / "sidecar.json").read_text())


def thread(env: Env, item: int) -> list:
    return [m for m in task_manager_store(env).item(item)["thread"] if m.get("category") != "status"]


def live_send(client, slug: str, **over: Any) -> Dict[str, Any]:
    body = {"client_round_id": str(uuid.uuid4()), "revision": "draft", "answers": [{"prompt": "layout", "options": ["b"]}], "note": "closer", **over}
    r = client.post(f"{BASE}/boards/{slug}/live/send", json=body)
    assert r.status_code == 200, r.text
    return r.json()



def test_a_version_1_sidecar_still_reads_and_is_written_back_unchanged(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    make_board(root)
    text = (root / SIDECAR["board"]["slug"] / "sidecar.json").read_text()
    parsed = document.parse_sidecar(json.loads(text))
    assert parsed.schema_version == 1 and parsed.live is None
    assert document.canonical_text(parsed) == text and "\"live\"" not in text
    assert scan.scan(root).exit_code == 0


def test_a_version_1_file_may_not_hold_a_live_slot_or_a_milestone() -> None:
    base = v1_sidecar()
    base["revisions"][0]["milestone"] = "first"
    with pytest.raises(document.SidecarInvalid, match="schema_version 2"):
        document.parse_sidecar(base)
    ok = v1_sidecar(schema_version=2)
    ok["revisions"][0]["milestone"] = "first"
    ok["revisions"][0]["inline_picks"] = True
    assert document.parse_sidecar(ok).revisions[0].milestone == "first"


def test_the_drafts_files_and_prompts_are_judged_like_a_revisions() -> None:
    raw = v1_sidecar(schema_version=2)
    view = {"id": "main", "label": "main", "file": "draft.html", "sha256": "a" * 64, "bytes": 5}
    draft = {"seq": 1, "updated_at": "2026-10-16T09:00:00Z", "summary": "s", "viewport": 320, "views": [view], "prompts": [], "anchors": []}
    raw["live"] = {"started_at": "2026-10-16T09:00:00Z", "by": {"actor": "claude"}, "draft": draft, "sends": [], "sends_total": 0}
    assert document.parse_sidecar(raw).live.draft.seq == 1
    for bad, match in (({"views": [{**view, "file": "draft--other.html"}]}, "draft.html"),
                       ({"views": [view, {**view, "file": "draft.html"}]}, "used twice"),
                       ({"prompts": [{"id": "p", "kind": "check", "label": "x", "anchor": "nope"}]}, "not declared")):
        broken = json.loads(json.dumps(raw))
        broken["live"]["draft"].update(bad)
        with pytest.raises(document.SidecarInvalid, match=match):
            document.parse_sidecar(broken)



def test_a_board_can_start_live_with_no_revision_and_the_task_is_left_alone(env: Env, client, item):
    before_state = task_manager_store(env).item(item)["state"]
    answer = start(client, item)
    slug = answer["slug"]
    assert answer["live"] is True and answer["seq"] == 1 and answer["started"] is True and answer["state"] == "live"
    data = side(env, slug)
    assert data["schema_version"] == 2 and data["revisions"] == [] and data["live"]["draft"]["views"][0]["file"] == "draft.html"
    assert (env.board(slug) / "draft.html").read_text() == PAGE_A
    assert task_manager_store(env).item(item)["state"] == before_state and thread(env, item) == []
    assert scan.scan(env.root).exit_code == 0 and scan.scan(env.root).findings == ()
    assert env.published.count("cplug.reviewboard.boards") == 1


def test_an_overwrite_replaces_the_draft_adds_no_revision_and_pushes_once(env: Env, client, item):
    slug = start(client, item)["slug"]
    env.published.clear()
    r = client.put(f"{BASE}/boards/{slug}/live", json=draft_body(html=PAGE_B, summary="second look"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["seq"] == 2 and out["started"] is False and out["changed"] is True
    data = side(env, slug)
    assert data["revisions"] == [] and data["live"]["draft"]["seq"] == 2 and data["live"]["draft"]["summary"] == "second look"
    assert (env.board(slug) / "draft.html").read_text() == PAGE_B
    assert env.published == ["cplug.reviewboard.boards"]
    assert thread(env, item) == [] and not list(env.board(slug).glob("r*.html"))
    again = client.put(f"{BASE}/boards/{slug}/live", json=draft_body(html=PAGE_B, summary="second look")).json()
    assert again["changed"] is False and again["seq"] == 2 and env.published == ["cplug.reviewboard.boards"]


def test_going_live_on_a_version_1_board_bumps_it_and_keeps_its_revisions(env: Env, client, item):
    made = client.post(f"{BASE}/boards", json=create_body(item)).json()
    slug = made["slug"]
    assert side(env, slug)["schema_version"] == 1
    state_before = task_manager_store(env).item(item)["state"]
    count = len(thread(env, item))
    out = client.put(f"{BASE}/boards/{slug}/live", json={"summary": "demo", "html": PAGE_A}).json()
    assert out["started"] is True and out["seq"] == 1
    data = side(env, slug)
    assert data["schema_version"] == 2 and [r["id"] for r in data["revisions"]] == ["r1"] and data["live"]["draft"]["viewport"] == 320
    assert task_manager_store(env).item(item)["state"] == state_before and len(thread(env, item)) == count


def test_a_view_the_overwrite_drops_loses_its_file_and_a_layer_board_is_refused(env: Env, client, item):
    slug = start(client, item, views=[{"id": "more", "label": "more", "html": "<p>more</p>"}])["slug"]
    assert (env.board(slug) / "draft--more.html").exists()
    client.put(f"{BASE}/boards/{slug}/live", json=draft_body(html=PAGE_B))
    assert not (env.board(slug) / "draft--more.html").exists() and scan.scan(env.root).findings == ()
    assert client.put(f"{BASE}/boards/{slug}/live", json=draft_body(layer={"kind": "questions"})).status_code == 422


def test_the_viewer_serves_the_draft_and_follows_an_overwrite(env: Env, client, item):
    slug = start(client, item)["slug"]
    ticket = client.post(f"{BASE}/boards/{slug}/revisions/draft/ticket", json={"view": "main"})
    assert ticket.status_code == 200, ticket.text
    page, name = viewer.page(env.root, slug, "draft", "main")
    assert b"send A" in page and b"rb" in page and name == "draft.html"
    client.put(f"{BASE}/boards/{slug}/live", json=draft_body(html=PAGE_B))
    assert b"send B" in viewer.page(env.root, slug, "draft", "main")[0]
    client.post(f"{BASE}/boards/{slug}/live/end", json={})
    with pytest.raises(BoardNotFound):
        viewer.page(env.root, slug, "draft", "main")


def test_a_page_written_ahead_of_its_row_is_read_after_one_more_look(env: Env, client, item, monkeypatch):
    slug = start(client, item)["slug"]
    real = viewer.load_sidecar
    calls = {"n": 0}

    def late_row(root, name):
        calls["n"] += 1
        if calls["n"] == 1:
            (env.board(slug) / "draft.html").write_text(PAGE_B)
        return real(root, name)

    monkeypatch.setattr(viewer, "load_sidecar", late_row)
    with pytest.raises(viewer.PageChanged):
        viewer.page(env.root, slug, "draft", "main")
    assert calls["n"] == 2



def test_a_milestone_freezes_the_draft_as_a_named_revision_and_hands_the_task_to_review(env: Env, client, item):
    slug = start(client, item)["slug"]
    out = client.post(f"{BASE}/boards/{slug}/live/milestone", json={"name": "icons only"}).json()
    assert out["revision"] == "r1" and out["milestone"] == "icons only" and out["unchanged"] is False and out["card"]["posted"] is True
    data = side(env, slug)
    row = data["revisions"][0]
    assert row["milestone"] == "icons only" and row["views"][0]["file"] == "r001.html" and data["live"]["draft"]["seq"] == 1
    assert (env.board(slug) / "r001.html").read_bytes() == (env.board(slug) / "draft.html").read_bytes()
    assert row["views"][0]["sha256"] == data["live"]["draft"]["views"][0]["sha256"]
    assert task_manager_store(env).item(item)["state"] == "review" and thread(env, item)[-1]["board"]["revision"] == "r1"
    assert scan.scan(env.root).findings == ()
    posted = len(thread(env, item))
    again = client.post(f"{BASE}/boards/{slug}/live/milestone", json={}).json()
    assert again["unchanged"] is True and len(side(env, slug)["revisions"]) == 1 and len(thread(env, item)) == posted
    client.put(f"{BASE}/boards/{slug}/live", json=draft_body(html=PAGE_B))
    second = client.post(f"{BASE}/boards/{slug}/live/milestone", json={}).json()
    assert second["revision"] == "r2" and second["milestone"] == "milestone 2"
    assert (env.board(slug) / "r001.html").read_text() == PAGE_A


def test_a_milestone_of_a_board_that_is_not_live_is_refused(env: Env, client, item):
    slug = client.post(f"{BASE}/boards", json=create_body(item)).json()["slug"]
    r = client.post(f"{BASE}/boards/{slug}/live/milestone", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_not_live"
    assert client.post(f"{BASE}/boards/{slug}/live/end", json={}).status_code == 409


def test_ending_drops_the_draft_and_its_files_and_posts_one_card(env: Env, client, item):
    slug = start(client, item)["slug"]
    out = client.post(f"{BASE}/boards/{slug}/live/end", json={"milestone": "final"}).json()
    assert out["ended"] is True and out["revision"] == "r1" and out["milestone"] == "final" and out["card"]["posted"] is True
    data = side(env, slug)
    assert "live" not in data and data["revisions"][0]["milestone"] == "final" and data["schema_version"] == 2
    assert not (env.board(slug) / "draft.html").exists() and scan.scan(env.root).findings == ()
    assert len([m for m in thread(env, item) if m.get("board")]) == 1 and task_manager_store(env).item(item)["state"] == "review"
    assert out["state"] == "your_turn"


def test_ending_a_board_that_never_had_a_milestone_posts_no_card(env: Env, client, item):
    slug = start(client, item)["slug"]
    out = client.post(f"{BASE}/boards/{slug}/live/end", json={}).json()
    assert out["revisions"] == 0 and out["card"]["posted"] is False and thread(env, item) == []
    assert out["state"] == "empty" and not list(env.board(slug).glob("draft*.html"))



def test_a_live_send_wakes_the_owning_session_and_leaves_the_task_alone(env: Env, client, item, told):
    slug = start_as_agent(env, item)
    client.post(f"{BASE}/boards/{slug}/live/milestone", json={})
    count, state_before = len(thread(env, item)), task_manager_store(env).item(item)["state"]
    out = live_send(client, slug)
    assert out["delivery"] == {"state": "told", "via": "channel"} and out["duplicate"] is False and out["send"]["n"] == 1
    assert told[0]["session"] == "ses_1"
    assert told[0]["text"].startswith("live send 1 on the draft (demo)") and "which button row: two rows" in told[0]["text"]
    assert "task_manager_board_get" in told[0]["text"]
    assert len(thread(env, item)) == count and task_manager_store(env).item(item)["state"] == state_before
    assert side(env, slug)["live"]["sends_total"] == 1 and side(env, slug)["rounds"] == []


def test_the_same_send_twice_tells_once_and_a_bad_answer_is_refused(env: Env, client, item, told):
    slug = start_as_agent(env, item)
    body = {"client_round_id": str(uuid.uuid4()), "revision": "draft", "answers": [{"prompt": "layout", "options": ["a"]}]}
    first = client.post(f"{BASE}/boards/{slug}/live/send", json=body).json()
    second = client.post(f"{BASE}/boards/{slug}/live/send", json=body).json()
    assert second["duplicate"] is True and second["send"] == first["send"] and len(told) == 1
    before = (env.board(slug) / "sidecar.json").read_bytes()
    bad = client.post(f"{BASE}/boards/{slug}/live/send", json={**body, "client_round_id": str(uuid.uuid4()), "answers": [{"prompt": "layout", "options": ["zzz"]}]})
    assert bad.status_code == 422 and (env.board(slug) / "sidecar.json").read_bytes() == before


def test_a_session_that_cannot_be_told_falls_back_to_the_task_so_nothing_is_lost(env: Env, client, item, monkeypatch):
    async def refused(self, session_id: str, text: str):
        return {"told": False, "reason": "the session is gone"}

    monkeypatch.setattr(board_port.BoardPort, "tell_session", refused)
    slug = start_as_agent(env, item)
    out = live_send(client, slug)
    assert out["delivery"]["state"] == "posted"
    message = thread(env, item)[-1]
    assert message["author"] == "joe" and message["text"].startswith("live send 1 on the draft")
    slug2 = start(client, item, slug_name="other")["slug"]
    assert live_send(client, slug2)["delivery"]["state"] == "posted"


def test_a_send_on_a_board_that_is_not_live_is_refused(env: Env, client, item, told):
    slug = client.post(f"{BASE}/boards", json=create_body(item)).json()["slug"]
    r = client.post(f"{BASE}/boards/{slug}/live/send", json={"client_round_id": str(uuid.uuid4()), "revision": "draft"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_not_live" and told == []


def test_only_the_newest_sends_are_kept_but_every_one_is_counted(env: Env, client, item, told):
    slug = start_as_agent(env, item)
    for _ in range(23):
        live_send(client, slug)
    live = side(env, slug)["live"]
    assert len(live["sends"]) == 20 and live["sends_total"] == 23 and live["sends"][0]["n"] == 4 and len(told) == 23


async def test_the_port_tells_a_session_through_the_guarded_delivery_and_reports_a_refusal() -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException

    delivered = []

    async def deliver(target, text, meta):
        delivered.append((target, text, meta))
        if target == "ses_gone":
            raise HTTPException(status_code=409, detail={"code": "session_gone", "detail": "no such session"})
        return SimpleNamespace(delivered_via="paste")

    port = board_port.BoardPort(SimpleNamespace(sessions=SimpleNamespace(deliver=deliver)))
    assert await port.tell_session("ses_1", "hi") == {"told": True, "via": "paste"}
    refused = await port.tell_session("ses_gone", "hi")
    assert refused["told"] is False and "no such session" in refused["reason"]



def test_the_agent_tools_run_a_live_session_from_start_to_end(env: Env, item):
    ok, started = env.call("task_manager_board_live_set", {"name": "demo", "title": "demo", "task": item, "summary": "first", "html": PAGE_A, "viewport": 320,
                                                          "prompts": PROMPTS, "anchors": ANCHORS, "inline_picks": True})
    assert ok, started
    slug = started["slug"]
    assert started["started"] is True and started["state"] == "live"
    assert side(env, slug)["live"]["draft"]["inline_picks"] is True and side(env, slug)["live"]["by"] == {"actor": "claude", "session": "ses_1"}
    ok, second = env.call("task_manager_board_live_set", {"board": slug, "summary": "second", "html": PAGE_B})
    assert ok and second["seq"] == 2 and second["started"] is False
    ok, got = env.call("task_manager_board_get", {"board": slug})
    assert ok and got["state"] == "live" and got["sidecar"]["live"]["draft"]["summary"] == "second"
    ok, marked = env.call("task_manager_board_milestone_add", {"board": slug, "name": "second look"})
    assert ok and marked["revision"] == "r1" and marked["milestone"] == "second look"
    ok, ended = env.call("task_manager_board_live_stop", {"board": slug})
    assert ok and ended["ended"] is True and ended["revisions"] == 1
    ok, listed = env.call("task_manager_boards_list", {"state": "live"})
    assert ok and listed["boards"] == []


def test_the_live_tools_refuse_a_bad_call_and_the_own_list_guard_applies(env: Env, item):
    ok, text = env.call("task_manager_board_live_set", {"board": "20261016-nothing", "summary": "x", "html": PAGE_A})
    assert not ok and "reviewboard_not_found" in text
    ok, text = env.call("task_manager_board_live_set", {"name": "demo", "title": "demo", "task": item, "summary": "x"})
    assert not ok and "exactly one of html" in text
    ok, text = env.call("task_manager_board_milestone_add", {"board": "20261016-nothing"})
    assert not ok and "reviewboard_not_found" in text
    other = task_manager_store(env).add("13", "theirs", actor="claude", title="theirs")["id"]
    ok, text = env.call("task_manager_board_live_set", {"name": "other", "title": "other", "task": other, "summary": "x", "html": PAGE_A, "viewport": 320})
    assert not ok and "cross_project" in text


def test_an_inline_picks_revision_is_a_version_2_revision(env: Env, client, item):
    out = client.post(f"{BASE}/boards", json=create_body(item, inline_picks=True)).json()
    data = side(env, out["slug"])
    assert data["schema_version"] == 2 and data["revisions"][0]["inline_picks"] is True and "live" not in data
    plain = client.post(f"{BASE}/boards", json=create_body(item, slug_name="plain")).json()
    assert side(env, plain["slug"])["schema_version"] == 1 and "inline_picks" not in side(env, plain["slug"])["revisions"][0]


def test_a_failed_overwrite_leaves_the_folder_untouched(env: Env, client, item):
    slug = start(client, item)["slug"]
    before = tree(env.root)
    r = client.put(f"{BASE}/boards/{slug}/live", json=draft_body(views=[{"id": "main", "label": "x", "html": "<p>x</p>"}]))
    assert r.status_code == 422 and tree(env.root) == before
