
from __future__ import annotations

import asyncio
import http.server
import subprocess
import threading
import time
from contextlib import closing

import pytest
import structlog
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from src.api.auth import limiter
from src.cplugs.huddle import schedule, wait_checks as checks, wait_runner, waits
from src.cplugs.huddle.rules import TaskManagerForbidden, TaskManagerInvalid
from src.cplugs.huddle.roles import unstick
from src.cplugs.sdk import app_info
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import env  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_waits import INSTALL, ROUTE, iso, park, question_of, runner_at, wait_row


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    limiter.reset()


@pytest.fixture(autouse=True)
def told(monkeypatch):
    seen: list = []

    async def tell(ctx, run, key, list_key):
        seen.append((key, list_key))
        return {"list": list_key, "status": "sent"}

    monkeypatch.setattr(unstick, "send_session", tell)
    return seen


def escalate(env, client) -> int:
    item = env.add(client)["id"]
    park(env.store, item)
    asyncio.run(runner_at(env, 2).expire_due())
    park(env.store, item, extend_reason="queued")
    asyncio.run(runner_at(env, 5).expire_due())
    assert wait_row(env.store, item)["status"] == "escalated"
    return item


def open_questions(env, item: int) -> list:
    return [m for m in env.store.item(item)["thread"] if m["kind"] == "question" and not m["answered"]]



def test_a_fork_cannot_set_waiting_on_either_side_and_the_schema_does_not_offer_it(manager):  # noqa: F811
    from src.core.mcp import tools

    store = huddle_store(manager)
    item = store.add("all", "parent", actor="joe")["id"]
    spec = next(d for d in tools.tool_definitions() if d["name"] == "task_manager_fork")["inputSchema"]["properties"]
    assert "waiting" not in spec["fork_state"]["enum"] and "waiting" not in spec["parent_state"]["enum"]
    for key in ("fork_state", "parent_state"):
        ok, text = call(manager, "task_manager_fork", {"item": item, key: "waiting"})
        assert not ok and "task_manager_update state waiting" in text
    ok, text = call(manager, "task_manager_batch_run", {"list_id": "all", "ops": [{"op": "fork", "item_id": item, "fork_state": "waiting"}]})
    assert not (ok and text["results"][0]["ok"])
    assert store.item(item)["state"] == "open"



def test_closing_the_stuck_question_without_choosing_reopens_the_task_and_an_agent_cannot_close_it(client, env):  # noqa: F811
    item = escalate(env, client)
    with pytest.raises(TaskManagerForbidden, match="owner answers"):
        env.store.mark_answered(item, actor="claude")
    assert env.store.item(item)["state"] == "waiting" and open_questions(env, item)
    env.store.mark_answered(item, actor="joe")
    assert env.store.item(item)["state"] == "open" and wait_row(env.store, item)["status"] == "ended"


def test_an_escalated_wait_has_a_backstop_that_asks_again_only_when_no_question_is_open(client, env):  # noqa: F811
    item = escalate(env, client)
    row = wait_row(env.store, item)
    assert row["deadline"] > time.time() + 20 * 3600
    assert asyncio.run(runner_at(env, 30).expire_due()) == 1
    assert len(open_questions(env, item)) == 1 and wait_row(env.store, item)["deadline"] > row["deadline"]
    with closing(env.store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_messages SET answered = 1 WHERE item_id = ? AND kind = 'question'", (item,))
    assert asyncio.run(runner_at(env, 60).expire_due()) == 1
    assert len(open_questions(env, item)) == 1 and env.store.item(item)["state"] == "waiting"



def test_the_agent_callback_obeys_cross_project_is_recorded_and_leaves_an_escalated_wait_to_the_owner(manager):  # noqa: F811
    store = huddle_store(manager)
    other = store.add("13", "another project's task", actor="joe")["id"]
    own = store.add("12", "mine", actor="joe")["id"]
    park(store, other)
    park(store, own)
    ok, text = call(manager, "task_manager_wait_update", {"item": other, "result": "cleared"})
    assert not ok and "cross_project" in text and store.item(other)["state"] == "waiting"
    ok, answer = call(manager, "task_manager_wait_update", {"item": other, "result": "cleared", "cross_project": True})
    assert ok and answer["state"] == "open"
    ok, answer = call(manager, "task_manager_wait_update", {"item": own, "result": "cleared"})
    assert ok
    with closing(store._connect(False)) as conn:
        ops = {(r["item_id"], r["op"], r["cross_project"]) for r in conn.execute("SELECT * FROM work_write_actors")}
    assert (other, "wait_resolve", 1) in ops and (own, "wait_resolve", 0) in ops
    stuck = store.add("12", "stuck", actor="joe")["id"]
    park(store, stuck)
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_item_waits SET status = 'escalated', extended = 1 WHERE item_id = ?", (stuck,))
    ok, text = call(manager, "task_manager_wait_update", {"item": stuck, "result": "cleared"})
    assert not ok and "he answers it" in text and store.item(stuck)["state"] == "waiting"


HANG_S = 3600
REAL_HANG_S = 30


class PassSignals:

    def __init__(self) -> None:
        self._passed = asyncio.Event()
        self._first = asyncio.Event()

    def done(self) -> None:
        self._passed.set()
        self._first.set()

    async def first_pass(self) -> None:
        await self._first.wait()

    async def next_pass(self) -> None:
        self._passed.clear()
        await self._passed.wait()


def watch_wait_passes(monkeypatch) -> PassSignals:
    signals = PassSignals()
    real = schedule.Scheduler.waits_due

    async def waits_due(self) -> int:
        try:
            return await real(self)
        finally:
            signals.done()

    monkeypatch.setattr(schedule.Scheduler, "waits_due", waits_due)
    return signals



def test_a_check_that_hangs_is_unknown_after_the_timeout(client, env, monkeypatch, tmp_path):  # noqa: F811
    item = env.add(client)["id"]
    park(env.store, item, wait_check={"kind": "file_exists", "path": str(tmp_path / "never")})

    async def hang(*args, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(checks, "run", hang)
    monkeypatch.setattr(wait_runner, "CHECK_TIMEOUT_S", 0.2)
    started = time.monotonic()
    assert asyncio.run(wait_runner.WaitRunner(env.ctx).run_checks()) == 1
    assert time.monotonic() - started < 3 and wait_row(env.store, item)["check_result"] == "unknown" and env.store.item(item)["state"] == "waiting"


def test_the_scheduler_still_expires_other_waits_while_a_check_hangs(client, env, monkeypatch, tmp_path):  # noqa: F811
    slow, due = env.add(client)["id"], env.add(client)["id"]
    park(env.store, slow, wait_check={"kind": "file_exists", "path": str(tmp_path / "never")})
    park(env.store, due)
    with closing(env.store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_item_waits SET deadline = ? WHERE item_id = ?", (time.time() - 5, due))
    signals = watch_wait_passes(monkeypatch)

    async def scenario():
        started = asyncio.Event()

        async def hang(*args, **kwargs):
            started.set()
            await asyncio.sleep(HANG_S)

        monkeypatch.setattr(checks, "run", hang)
        monkeypatch.setattr(wait_runner, "CHECK_TIMEOUT_S", HANG_S)
        schedule.start(env.ctx)
        try:
            await asyncio.wait_for(started.wait(), REAL_HANG_S)
            await asyncio.wait_for(signals.first_pass(), REAL_HANG_S)
            assert schedule._scheduler._check_task is not None and not schedule._scheduler._check_task.done()
            return env.store.item(due)["state"]
        finally:
            schedule.stop()

    assert asyncio.run(scenario()) == "open"



def test_url_ok_never_goes_through_a_proxy_from_the_environment(monkeypatch):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    try:
        assert checks.check_url(checks.parse({"kind": "url_ok", "url": f"http://127.0.0.1:{server.server_address[1]}/"})).status == checks.PASS
    finally:
        server.shutdown()



def test_the_public_callback_is_rate_limited_and_a_refusal_is_a_debug_line(client, env, default_structlog):  # noqa: F811
    client.app.state.limiter = limiter
    client.app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    item = env.add(client)["id"]
    park(env.store, item)
    with structlog.testing.capture_logs() as logs:
        codes = [client.post(ROUTE.format(item), json={"token": "wrong", "result": "cleared"}).status_code for _ in range(22)]
    assert codes[:20] == [403] * 20 and codes[20:] == [429, 429]
    refused = [e for e in logs if e["event"] == "task_manager_wait_callback_refused"]
    assert refused and {e["log_level"] for e in refused} == {"debug"}



def test_moving_a_task_open_and_parking_it_again_cannot_reset_the_one_extension(client, env):  # noqa: F811
    item = env.add(client)["id"]
    park(env.store, item)
    env.store.update(item, actor="claude", state="open")
    with pytest.raises(TaskManagerInvalid, match="extend_reason"):
        park(env.store, item)
    park(env.store, item, extend_reason="still blocked")
    env.store.update(item, actor="claude", state="open")
    with pytest.raises(TaskManagerInvalid, match="parked 2 times"):
        park(env.store, item, extend_reason="and again")
    env.store.update(item, actor="claude", state="review")
    other = env.add(client)["id"]
    park(env.store, other)
    env.store.update(other, actor="claude", state="review")
    assert park(env.store, other)["wait"]["extended"] == 0


def test_a_soft_delete_ends_the_live_wait_and_kills_its_token(client, env):  # noqa: F811
    item = env.add(client)["id"]
    token = park(env.store, item)["wait_token"]
    with closing(env.store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET deleted = 1 WHERE id = ?", (item,))
    row = wait_row(env.store, item)
    assert row["status"] == "ended" and row["token_hash"] == "" and waits.WaitStore(env.store).verify(item, token) is None
    assert waits.WaitStore(env.store).due_expiries(time.time() + 10 ** 7) == []



def test_parking_and_tagging_in_one_call_keeps_the_callback_token(manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    ok, answer = call(manager, "task_manager_update", {"item": item, "state": "waiting", "tag": "me", **INSTALL}, raw=True)
    assert ok and len(answer["wait_callback"]["token"]) >= 40


def test_an_in_place_extension_keeps_the_check_unless_it_brings_a_new_one(client, env, tmp_path):  # noqa: F811
    item = env.add(client)["id"]
    park(env.store, item, wait_check={"kind": "file_exists", "path": str(tmp_path / "a")})
    kept = park(env.store, item, expect_by=iso(7200), extend_reason="one more hour")
    assert kept["wait"]["check_kind"] == "file_exists" and wait_row(env.store, item)["check_json"].find("/a") > 0
    other = env.add(client)["id"]
    park(env.store, other, wait_check={"kind": "file_exists", "path": str(tmp_path / "a")})
    swapped = park(env.store, other, expect_by=iso(7200), extend_reason="new check", wait_check={"kind": "version_live", "version": "9.9.9"})
    assert swapped["wait"]["check_kind"] == "version_live" and wait_row(env.store, other)["check_runs"] == 0


def test_the_repo_root_comes_from_the_environment_and_an_install_with_no_repo_says_so(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    sha = "a" * 40
    check = checks.parse({"kind": "git_contains", "repo": str(repo), "ref": "main", "sha": sha})
    monkeypatch.setenv("CARNIVORE_REPO_ROOT", str(repo))
    assert app_info.repo_root() == repo and checks.app_repo_roots()[0] == repo.resolve()
    assert checks.check_git(check).status != checks.PASS
    monkeypatch.setenv("CARNIVORE_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr("src.core.version.repo_root", lambda: tmp_path / "installed")
    assert app_info.repo_root() is None and checks.app_repo_roots() == []
    verdict = checks.check_git(check)
    assert verdict.status == checks.UNKNOWN and verdict.what == checks.NO_REPO



def test_a_failed_hand_back_after_expiry_reopens_the_wait_instead_of_stranding_the_task(env, client, monkeypatch):  # noqa: F811
    from src.cplugs.huddle.rules import TaskManagerInvalid

    item = env.add(client)["id"]
    park(env.store, item)

    def refuse(store, item_id, text, detail, expected_revision=None):
        raise TaskManagerInvalid("a rule refuses the move")

    monkeypatch.setattr(wait_runner, "hand_back", refuse)
    asyncio.run(runner_at(env, 2).expire_due())
    row = wait_row(env.store, item)
    assert row["status"] == "active", "the wait was left ended while the task still waits: nothing would ever wake it"
    assert row["deadline"] > time.time() + 200
    assert env.store.item(item)["state"] == "waiting"
