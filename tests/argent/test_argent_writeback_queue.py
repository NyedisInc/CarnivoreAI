
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import HTTPException

from src.api.argent import writeback as routes
from src.config import settings as app_settings
from src.core.argent import classifier, notices, timeline, work_items, writeback, writeback_template
from src.core.argent.client import ArgentClient
from src.core.argent.device_login import DeviceLogin
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.plugins.sdk import ports

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "argent"
SERVER = "https://cp.argent.test"
LEAK = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 3
COMMIT = {"sha": "abc1234", "subject": "fix the token refresh", "files": ["src/auth.py", "/Users/x/abs.py"], "file_count": 2}


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class World:

    def __init__(self) -> None:
        self.mode, self.http, self.prompts, self.notes = "up", [], [], []
        self.beast = False
        self.keys = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.http.append((request.method, request.url.path, body))
        self.keys.append(request.headers.get("idempotency-key"))
        if request.url.path.endswith(("/writeback", "/close")):
            if self.mode == "bad_status":
                return httpx.Response(400, json={"error": {"code": "bad_status"}})
            if self.mode == "label":
                return httpx.Response(200, json={"ok": True, "status_refused": "in review"})
            if self.mode == "throttled":
                return httpx.Response(429, headers={"Retry-After": "900"}, json={"error": "rate_limited"})
            if self.mode == "not_connected":
                return httpx.Response(409, json={"error": {"code": "tracker.not_connected"}})
            if self.mode == "secret":
                return httpx.Response(422, json={"error": {"code": "secret_detected"}})
            if self.mode == "down":
                raise httpx.ConnectError("down")
            name = "writeback_status_refused.json" if self.mode == "refused" else "writeback_ok.json"
            return httpx.Response(200, json=json.loads((FIXTURES / name).read_text()))
        if request.url.path == "/v1/my/cost":
            return httpx.Response(200, json={"items": [{"id": "wi_story1", "cost_micros": 1234500}]})
        return httpx.Response(200, json={"ok": True})

    def client(self) -> ArgentClient:
        return ArgentClient(SERVER, lambda: "FIXTURE-asicli-not-a-secret", transport=httpx.MockTransport(self.handler))

    async def chat(self, feature: str, prompt: str, **options: Any) -> Any:
        self.prompts.append(prompt)
        return SimpleNamespace(text="Fixed the token refresh.", usage=SimpleNamespace(input_tokens=40, output_tokens=9), raw={"model": "fixture-model"})

    def posted(self) -> List[Dict[str, Any]]:
        return [b for m, p, b in self.http if m == "POST" and p.endswith("/writeback")]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"argent": {"serverUrl": SERVER, "enabled": False}}))
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "auth_config_file", str(config))
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    app_settings.drop_auth_config_cache()
    w = World()
    store, tokens = ArgentStore(state), TokenStore(Keychain())
    store.set_login("ten_1", "id_1", "Fixture Person", 3600)
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens)))
    work_items.replace_all("ten_1", json.loads((FIXTURES / "work_items_page.json").read_text())["items"], 7)
    monkeypatch.setattr(writeback, "beast_armed", lambda: w.beast)
    monkeypatch.setattr(writeback, "install_id", lambda: "install-fixture")
    monkeypatch.setattr(notices, "writeback_review", lambda *a: w.notes.append(("review", *a)))
    monkeypatch.setattr(notices, "writeback_refused", lambda *a: w.notes.append(("refused", *a)))
    monkeypatch.setattr(notices, "writeback_tracker_newer", lambda *a: w.notes.append(("tracker_newer", *a)))
    monkeypatch.setattr(notices, "writeback_blocked_secret", lambda *a: w.notes.append(("blocked", *a)))
    monkeypatch.setattr(notices, "writeback_review_resolved", lambda *a: None)
    yield w
    set_runtime(None)
    ports.unregister(PORT_NAME)


def queue(commit: Dict[str, Any] = COMMIT, now: float = 1000.0, item: str = "wi_story1", milestone: str = writeback.COMMIT) -> int:
    return writeback.enqueue_milestone("ten_1", "ref_1", "carnivore_api", "api", item, milestone, [commit], now=now)


def run(w: World, now: float) -> None:
    asyncio.run(writeback.run_pass(w.client(), "ten_1", now=now, chat=w.chat))


def rows(state: str) -> List[Dict[str, Any]]:
    import sqlite3
    from contextlib import closing

    from src.core.argent import store

    with closing(store.open_db()) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM writeback WHERE state = ?", (state,))]


def test_the_body_is_one_capped_line_with_relative_paths_only() -> None:
    body = writeback_template.build("t" * 500, "Ann", "api", ["s" * 900] * 9, 9, ["a.py", "/etc/passwd", "../x", "b.py"] + ["c.py"] * 20, 4, "$0.12", "x" * 5000)
    assert len(body) <= writeback_template.MAX_BODY and "\n" not in body
    assert "/etc/passwd" not in body and "../x" not in body and body.count("; ") <= 4
    short = writeback_template.build("login", "Ann", "api", ["fix x"], 1, ["a.py"], 1, "$0.12", "fixed x.")
    assert short == "login | Ann's session api | commits: 1 (fix x) | files: 1 (a.py) | cost this window: $0.12 | fixed x."


def test_beast_on_posts_and_off_waits_in_review(world: World) -> None:
    world.beast = True
    queue()
    run(world, 1000.0)
    assert len(world.posted()) == 1 and world.posted()[0]["kind"] == "comment" and rows("posted")
    body = world.posted()[0]["body"]
    assert body.startswith("Fixture Story | Fixture Person's session api | commits: 1 (fix the token refresh)") and "src/auth.py" in body and "/Users/x" not in body
    assert "$1.23" in body and body.endswith("Fixed the token refresh.")
    spend = [b for m, p, b in world.http if p.endswith("/usage")]
    assert spend and spend[0]["turns"][0]["tag"] == "carnivore-internal"
    world.beast = False
    queue(dict(COMMIT, sha="def5678"), now=1700.0)
    run(world, 1700.0)
    assert len(world.posted()) == 1 and len(rows("review")) == 1 and world.notes[-1][0] == "review"


def test_a_comment_waiting_stays_waiting_when_beast_turns_on_and_a_posted_one_is_not_held(world: World) -> None:
    queue()
    run(world, 1000.0)
    assert len(rows("review")) == 1
    world.beast = True
    run(world, 1100.0)
    run(world, 99999.0)
    assert world.posted() == [] and len(rows("review")) == 1
    queue(dict(COMMIT, sha="def5678"), now=2000.0)
    run(world, 2000.0 + writeback.WINDOW_SECONDS)
    world.beast = False
    assert len(world.posted()) == 1 and rows("posted")


def test_edit_then_approve_posts_the_edited_text_and_an_edit_with_a_secret_is_refused(world: World) -> None:
    row_id = queue()
    run(world, 1000.0)
    with pytest.raises(writeback.EditError) as refused:
        writeback.edit("ten_1", row_id, "see " + LEAK)
    assert refused.value.code == "blocked_secret" and "sk-ant" not in rows("review")[0]["body"]
    writeback.edit("ten_1", row_id, "reviewed by hand: the refresh fix is in")
    writeback.approve("ten_1", row_id)
    run(world, 1001.0)
    assert [b["body"] for b in world.posted()] == ["reviewed by hand: the refresh fix is in"]
    with pytest.raises(writeback.EditError) as gone:
        writeback.approve("ten_1", row_id)
    assert gone.value.code == "not_in_review"


def test_discard_never_posts(world: World) -> None:
    row_id = queue()
    run(world, 1000.0)
    writeback.discard("ten_1", row_id)
    world.beast = True
    run(world, 5000.0)
    assert world.posted() == [] and rows("discarded")


def test_one_comment_per_item_per_ten_minutes_and_a_burst_is_one_comment(world: World) -> None:
    world.beast = True
    queue(now=1000.0)
    run(world, 1000.0)
    second = queue(dict(COMMIT, sha="d1"), now=1100.0)
    assert queue(dict(COMMIT, sha="d2"), now=1200.0) == second
    run(world, 1300.0)
    assert len(world.posted()) == 1
    run(world, 1000.0 + writeback.WINDOW_SECONDS)
    assert len(world.posted()) == 2 and "commits: 2" in world.posted()[1]["body"]


def test_a_secret_never_reaches_the_helper_ai_or_argent_and_the_check_is_what_blocks_it(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.beast = True
    queue(dict(COMMIT, subject="use " + LEAK))
    run(world, 1000.0)
    assert world.prompts == [] and world.posted() == [] and rows("blocked") and world.notes[-1][0] == "blocked"
    assert not any(LEAK in json.dumps(b) for _m, _p, b in world.http) and not any(LEAK in p for p in world.prompts)
    monkeypatch.setattr(classifier, "has_secret", lambda *texts: 0)
    queue(dict(COMMIT, sha="def5678", subject="use " + LEAK), now=3000.0)
    run(world, 3000.0)
    assert any(LEAK in p for p in world.prompts) or any(LEAK in b["body"] for b in world.posted())


def test_a_status_refusal_tells_the_developer_and_a_failed_post_is_retried_later(world: World) -> None:
    world.beast = True
    world.mode = "refused"
    queue()
    run(world, 1000.0)
    assert rows("posted")[0]["result"] == "status_refused" and world.notes[-1][0] == "refused"
    world.mode = "down"
    queue(dict(COMMIT, sha="def5678"), now=2000.0)
    run(world, 2000.0 + writeback.WINDOW_SECONDS)
    assert len(rows("ready")) == 1 and rows("ready")[0]["attempts"] == 1
    run(world, 2000.0 + writeback.WINDOW_SECONDS + 1)
    assert rows("ready")[0]["attempts"] == 1
    world.mode = "up"
    run(world, 2000.0 + writeback.WINDOW_SECONDS + writeback.BACKOFF_SECONDS + 1)
    assert len(rows("posted")) == 2


def test_a_session_end_brings_its_waiting_comment_due(world: World) -> None:
    world.beast = True
    queue(now=1000.0)
    run(world, 1000.0)
    queue(dict(COMMIT, sha="d1"), now=1100.0)
    run(world, 1200.0)
    assert len(world.posted()) == 1
    assert writeback.end_session("carnivore_api", now=1250.0) == 1
    run(world, 1250.0)
    assert len(world.posted()) == 2


def test_feature_off_runs_nothing_answers_empty_and_takes_no_approval(world: World) -> None:
    assert not writeback.is_running()
    assert asyncio.run(routes.get_review()) == {"enabled": False, "items": []}
    for call in (routes.post_approve(1), routes.post_discard(1)):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(call)
        assert refused.value.status_code == 409 and refused.value.detail["code"] == "feature_off"
    assert rows("collecting") == [] and not timeline.is_running()
    ports.register(PORT_NAME, {"on": True})
    row_id = queue()
    run(world, 1000.0)
    assert asyncio.run(routes.get_review())["items"][0]["id"] == row_id
    assert asyncio.run(routes.post_approve(row_id))["state"] == "ready"


def test_a_secret_cut_by_the_80_character_subject_limit_is_still_blocked(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.beast = True
    subject = "x" * 70 + " " + LEAK
    assert classifier.has_secret(writeback_template.build("t", "a", "n", [subject], 1, [], 0, "-", "")) == 0, "the truncated body alone passes the detector"
    queue(dict(COMMIT, subject=subject))
    run(world, 1000.0)
    assert world.posted() == [] and rows("blocked") and world.notes[-1][0] == "blocked"
    monkeypatch.setattr(classifier, "has_secret", lambda *texts: sum(len(classifier.scan_text(t)) for t in texts[-1:] if t))
    queue(dict(COMMIT, sha="def5678", subject=subject), now=3000.0)
    run(world, 3000.0)
    assert world.posted() and "sk-ant-ap" in world.posted()[0]["body"]


def test_a_writeback_carries_a_stable_per_row_idempotency_key(world: World) -> None:
    import re
    import sqlite3

    world.beast = True
    first, second = queue(now=1000.0), queue(dict(COMMIT, sha="d2"), now=1000.0, item="wi_story2")
    run(world, 1000.0)
    assert len(world.keys) >= 2 and all(re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", k or "") for k in world.keys if k)
    posts = [k for (m, p, _b), k in zip(world.http, world.keys) if p.endswith("/writeback")]
    assert len(posts) == 2 and posts[0] != posts[1] and all(re.fullmatch(r"cwb-[0-9a-f]{40}", k) for k in posts)
    row = sqlite3.Row
    from contextlib import closing

    from src.core.argent import store

    with closing(store.open_db()) as conn:
        conn.row_factory = row
        one, two = (conn.execute("SELECT * FROM writeback WHERE id = ?", (i,)).fetchone() for i in (first, second))
    assert writeback.idempotency_key("ten_1", one) == writeback.idempotency_key("ten_1", one) == posts[0]
    assert writeback.idempotency_key("ten_1", two) == posts[1]


def test_a_429_keeps_the_comment_ready_until_retry_after_and_resends_the_same_key(world: World) -> None:
    world.beast = True
    world.mode = "throttled"
    queue()
    run(world, 1000.0 + writeback.WINDOW_SECONDS)
    row = rows("ready")[0]
    assert row["attempts"] == 1 and row["next_try"] >= 1000.0 + writeback.WINDOW_SECONDS + 900
    world.mode = "up"
    run(world, row["next_try"] - 1)
    assert len(rows("posted")) == 0
    run(world, row["next_try"])
    keys = [k for (m, p, _b), k in zip(world.http, world.keys) if p.endswith("/writeback")]
    assert len(rows("posted")) == 1 and len(keys) == 2 and keys[0] == keys[1]


def test_a_disconnected_tracker_holds_the_comment_but_a_422_or_other_4xx_is_final(world: World) -> None:
    world.beast = True
    world.mode = "not_connected"
    queue()
    run(world, 1000.0 + writeback.WINDOW_SECONDS)
    assert rows("ready")[0]["attempts"] == 1 and not rows("failed")
    world.mode = "secret"
    queue(dict(COMMIT, sha="d3"), now=5000.0, item="wi_story2")
    run(world, 5000.0 + writeback.WINDOW_SECONDS)
    assert {r["item_id"]: r["result"] for r in rows("failed")}["wi_story2"] == "secret_detected"



def move(milestone: str, item: str = "wi_story1", **over: Any) -> int:
    return writeback.enqueue_move("ten_1", item, milestone, now=1000.0, **over)


def moves(world: World, suffix: str) -> List[Dict[str, Any]]:
    return [b for m, p, b in world.http if m == "POST" and p.endswith(suffix)]


def test_a_close_row_is_sent_at_once_with_beast_off_to_the_close_route(world: World) -> None:
    assert not world.beast
    move(writeback.MOVE_CLOSE, reason="all validated")
    run(world, 1000.0)
    assert moves(world, "/work-items/wi_story1/close") == [{"reason": "all validated", "comment": False}] and rows("posted") and not rows("review")
    assert world.keys[-1] and world.keys[-1].startswith("cwb-")


def test_a_picked_row_sends_a_status_writeback_with_the_milestone_and_no_to_status(world: World) -> None:
    move(writeback.MOVE_PICKED, session_id="ref_1")
    run(world, 1000.0)
    assert moves(world, "/work-items/wi_story1/writeback") == [{"kind": "status", "milestone": "picked", "session_id": "ref_1"}] and rows("posted")


def test_a_second_unsent_row_for_the_same_item_and_move_is_the_same_row(world: World) -> None:
    assert move(writeback.MOVE_CLOSE) == move(writeback.MOVE_CLOSE) and move(writeback.MOVE_PICKED) != move(writeback.MOVE_CLOSE)
    run(world, 1000.0)
    assert len(moves(world, "/close")) == 1


def test_a_failed_close_is_kept_and_retried_on_the_queue_schedule(world: World) -> None:
    world.mode = "down"
    move(writeback.MOVE_CLOSE)
    run(world, 1000.0)
    assert len(rows("ready")) == 1 and rows("ready")[0]["attempts"] == 1
    run(world, 1001.0)
    assert len(moves(world, "/close")) == 1
    world.mode = "up"
    run(world, 1000.0 + writeback.BACKOFF_SECONDS + 1)
    assert len(rows("posted")) == 1


def test_a_picked_row_that_gets_400_waits_then_gives_up_quietly(world: World) -> None:
    world.mode = "bad_status"
    move(writeback.MOVE_PICKED)
    moment = 1000.0
    for _ in range(writeback.MAX_ATTEMPTS):
        run(world, moment)
        moment += writeback.MAX_BACKOFF + 1
    assert len(moves(world, "/writeback")) == writeback.MAX_ATTEMPTS and rows("failed")[0]["result"] == "gave_up" and world.notes == []


def test_a_status_refused_close_names_the_story_and_the_trackers_state(world: World) -> None:
    world.mode = "label"
    move(writeback.MOVE_CLOSE)
    run(world, 1000.0)
    assert world.notes == [("tracker_newer", rows("posted")[0]["id"], "Fixture Story", "in review")]
    world.mode = "refused"
    move(writeback.MOVE_PICKED, item="wi_story1")
    run(world, 1001.0)
    assert world.notes[-1][3] == ""
