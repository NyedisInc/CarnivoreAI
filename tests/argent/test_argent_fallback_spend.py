
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.core.argent import fallback_spend as fs
from src.core.argent import row_state
from src.core.argent import settings as argent_settings
from src.core.argent.client import ArgentClient, Unauthorized, parse_retry_after
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.session_token_usage import per_request
from src.core.session_token_usage.reader import SessionSubject
from src.core.stat_gate import dir_names

ROOT = Path(__file__).resolve().parents[2]
IDS = json.loads((ROOT / "tests" / "fixtures" / "argent" / "usage_request_ids.json").read_text())
CONV = "11111111-2222-3333-4444-555555555555"
METERED = IDS["items"][0]


def _line(request_id, at, agent=""):
    return json.dumps({"type": "assistant", "requestId": request_id, "timestamp": at, "message": {
        "id": "m_" + request_id, "model": "claude-opus-4-5", "usage": {
            "input_tokens": 1, "output_tokens": 2, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4}}}) + "\n"


def _stamp(n):
    return f"2026-11-05T10:{n // 60:02d}:{n % 60:02d}Z"


class Argent:

    def __init__(self, post_status=(200,), lookup_status=200):
        self.posts, self.lookups, self.post_status, self.lookup_status, self.calls = [], [], list(post_status), lookup_status, 0
        self.error_body, self.retry_after, self.bodies = {}, None, []

    def transport(self):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                self.lookups.append(dict(request.url.params))
                return httpx.Response(self.lookup_status, json=IDS)
            self.calls += 1
            status = self.post_status.pop(0) if len(self.post_status) > 1 else self.post_status[0]
            self.bodies.append(request.content)
            if status == 200:
                self.posts.append(json.loads(request.content))
            return httpx.Response(status, headers={"Retry-After": self.retry_after} if self.retry_after and status == 429 else {}, json=self.error_body if status == 404 else ({"error": "rate limit exceeded"} if status == 429 else  ({"work_item_ignored": True} if status == 200 else {})))
        return httpx.MockTransport(handle)


@pytest.fixture
def world(tmp_path):
    per_request.clear()
    dir_names.clear()
    main = tmp_path / "projects" / "-w" / f"{CONV}.jsonl"
    main.parent.mkdir(parents=True)
    main.write_text("")
    session = fs.SpendSession("12", SessionSubject("claude", CONV, "/w"))
    cursors = fs.CursorStore(tmp_path)

    def write(*lines):
        with open(main, "a") as handle:
            handle.writelines(lines)

    async def no_sleep(_):
        return None

    def run(argent, **kw):
        client = ArgentClient("https://cp.argent.test", lambda: "FIXTURE-token", transport=argent.transport())
        return asyncio.run(fs.report_session(client, "ten_1", session, cursors, sleep=no_sleep, projects_dir=tmp_path / "projects", **kw))

    return SimpleNamespace(write=write, run=run, cursors=cursors, session=session, tmp=tmp_path)


def test_batches_of_200_skip_metered_and_resume_from_the_cursor(world):
    world.write(_line(METERED, _stamp(0)), *[_line(f"req_{i}", _stamp(i + 1)) for i in range(450)])
    argent = Argent()
    assert world.run(argent) == 450
    assert [len(p["turns"]) for p in argent.posts] == [200, 200, 50]
    sent = [t["request_id"] for p in argent.posts for t in p["turns"]]
    assert METERED not in sent and len(set(sent)) == 450
    assert world.cursors.get("ten_1", "12") == _stamp(450)
    again = Argent()
    assert world.run(again) == 0 and again.posts == [] and again.lookups == []
    world.write(_line("req_new", _stamp(500)))
    third = Argent()
    assert world.run(third) == 1 and third.posts[0]["turns"][0]["request_id"] == "req_new"
    assert third.lookups[0]["since"] == _stamp(450)


def test_a_batch_boundary_never_splits_a_run_of_equal_timestamps(world):
    rows = [SimpleNamespace(timestamp=t) for t in ("a", "b", "b")]
    assert fs._safe_cursor(rows[:2], rows[2]) == "a"
    assert fs._safe_cursor(rows[:2], None) == "b"


def test_turn_carries_sub_agent_and_work_item_tags(world):
    world.write(_line("req_root", _stamp(1)))
    argent = Argent()
    world.run(argent, work_item_for=lambda row: "wi_9")
    turn = argent.posts[0]["turns"][0]
    assert (turn["sub_agent_id"], turn["work_item_id"], turn["input_tokens"], turn["cache_read_tokens"]) == ("", "wi_9", 1, 4)
    plain = Argent()
    world.write(_line("req_two", _stamp(2)))
    world.run(plain)
    assert "work_item_id" not in plain.posts[0]["turns"][0]


def test_failed_lookup_posts_nothing_and_a_leaking_variant_would_post(world):
    world.write(_line("req_a", _stamp(1)))
    argent = Argent(lookup_status=503)
    assert world.run(argent) == 0 and argent.posts == [] and world.cursors.get("ten_1", "12") is None
    leaking = Argent()
    assert asyncio.run(fs._post_batch(ArgentClient("https://cp.argent.test", transport=leaking.transport()), "12", [{"request_id": "x"}], lambda _: asyncio.sleep(0))) is True
    assert leaking.posts


def test_5xx_retries_then_succeeds_and_400_does_not_retry(world):
    world.write(_line("req_a", _stamp(1)))
    flaky = Argent(post_status=(503, 503, 200))
    assert world.run(flaky) == 1 and flaky.calls == 3
    world.write(_line("req_b", _stamp(2)))
    refused = Argent(post_status=(400,))
    assert world.run(refused) == 1 and refused.calls == 1
    world.write(_line("req_c", _stamp(3)))
    down = Argent(post_status=(503,))
    assert world.run(down) == 0 and down.calls == fs.RETRIES and world.cursors.get("ten_1", "12") == _stamp(2)


def test_429_waits_retry_after_and_resends_the_same_body_and_a_long_ask_stays_queued(world):
    world.write(_line("req_a", _stamp(1)))
    waits = []

    async def record(seconds):
        waits.append(seconds)

    limited = Argent(post_status=(429, 200))
    limited.retry_after = "60"
    client = ArgentClient("https://cp.argent.test", lambda: "FIXTURE-token", transport=limited.transport())
    assert asyncio.run(fs._post_batch(client, "12", [{"request_id": "req_a"}], record)) is True
    assert waits == [60.0] and limited.calls == 2 and len(set(limited.bodies)) == 1 and limited.posts
    waits.clear()
    slow = Argent(post_status=(429,))
    slow.retry_after = "600"
    client = ArgentClient("https://cp.argent.test", lambda: "FIXTURE-token", transport=slow.transport())
    assert asyncio.run(fs._post_batch(client, "12", [{"request_id": "req_a"}], record)) is False
    assert waits == [] and slow.calls == 1
    bare = Argent(post_status=(429,))
    client = ArgentClient("https://cp.argent.test", lambda: "FIXTURE-token", transport=bare.transport())
    assert asyncio.run(fs._post_batch(client, "12", [{"request_id": "req_a"}], record)) is False
    assert waits == [1.0, 3.0] and bare.calls == fs.RETRIES
    assert parse_retry_after("60") == 60.0 and parse_retry_after("Wed, 21 Oct 2099 07:28:00 GMT") is None and parse_retry_after("soon") is None and parse_retry_after(None) is None


def test_401_marks_the_login_expired_and_ends_the_pass(world):
    store = ArgentStore(world.tmp)
    store.set_login("ten_1", "id_1", "Sam", 3600)
    marks = []
    world.write(_line("req_a", _stamp(1)))
    argent = Argent(post_status=(401,))
    client = ArgentClient("https://cp.argent.test", lambda: "FIXTURE-token", transport=argent.transport(), on_unauthorized=lambda: (store.mark_login_expired(), marks.append(1)))
    with pytest.raises(Unauthorized):
        asyncio.run(fs.report_session(client, "ten_1", world.session, world.cursors, projects_dir=world.tmp / "projects"))
    assert marks == [1] and store.login_expired() is True


def test_off_posts_nothing_and_the_loop_runs_only_while_the_feature_is_on(world, monkeypatch):
    called = []

    async def source():
        called.append(1)
        return [world.session]

    store = ArgentStore(world.tmp)
    store.set_login("ten_1", "id_1", "Sam", 3600)
    set_runtime(Runtime(store=store, tokens=SimpleNamespace(read=lambda t: "FIXTURE-token"), login=None))
    monkeypatch.setattr(argent_settings, "read", lambda: argent_settings.ArgentSettings(server_url="https://cp.argent.test", enabled=False))
    assert asyncio.run(fs.run_pass(source, world.cursors)) == 0 and called == []
    monkeypatch.setattr(argent_settings, "read", lambda: argent_settings.ArgentSettings(server_url="https://cp.argent.test", enabled=True))
    monkeypatch.setattr(fs, "_client", lambda tenant: ArgentClient("https://cp.argent.test", transport=Argent().transport()))
    asyncio.run(fs.run_pass(source, world.cursors))
    assert called == [1]
    assert fs.is_running() is False
    set_runtime(None)


def test_404_on_the_post_matches_the_siblings_and_work_item_ignored_is_success(world):
    world.write(_line("req_a", _stamp(1)))
    bare = Argent(post_status=(404,))
    assert world.run(bare) == 0 and world.cursors.get("ten_1", "12") is None
    own = Argent(post_status=(404,))
    own.error_body = {"error": {"code": "not_found"}}
    assert world.run(own) == 1 and world.cursors.get("ten_1", "12") == _stamp(1)
    world.write(_line("req_b", _stamp(2)))
    ok = Argent()
    assert world.run(ok) == 1 and world.cursors.get("ten_1", "12") == _stamp(2)


def test_a_gateway_routed_turn_is_not_posted_and_a_bypassed_one_is(world):
    mint = fs._epoch(_stamp(5))
    for name, tethered in (("carnivore_gw", True), ("carnivore_direct", False)):
        row_state.record_launch("ten_1", name, working_dir="/w", tethered=tethered, reason="" if tethered else "gateway down", key_id="k_" + name, clock=lambda: mint)
        row_state.confirm("ten_1", name, clock=lambda: mint)
        if tethered:
            row_state.first_traffic("ten_1", name, seen=True, unmetered_at=0, now=mint)
    world.write(_line("req_before", _stamp(1)), _line("req_after", _stamp(10)))
    for tmux, expected in (("carnivore_gw", {"req_before"}), ("carnivore_direct", {"req_before", "req_after"}), ("carnivore_none", {"req_before", "req_after"})):
        world.session = fs.SpendSession("12", world.session.subject, tmux)
        world.cursors.set("ten_1", "12", "")
        argent = Argent()
        asyncio.run(fs.report_session(ArgentClient("https://cp.argent.test", transport=argent.transport()), "ten_1", world.session, world.cursors,
                                      sleep=lambda _: asyncio.sleep(0), projects_dir=world.tmp / "projects"))
        assert {t["request_id"] for p in argent.posts for t in p["turns"]} == expected, tmux
