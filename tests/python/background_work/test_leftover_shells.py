
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import session_background_work_routes as routes
from src.api.parked_work_listing import background_processes_for
from src.core.background_work import leftovers as lo
from src.core.background_work.attribution import LaunchOwners
from src.core.background_work.listing import ListedProcess
from src.core.background_work.measured import STATE_RUNNING, BackgroundMeasure
from src.core.background_work.open_count import BackgroundCountReader
from src.core.attention.turn_counts import KIND_SHELL
from src.core.subagents.parked_launches import OpenLaunch

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _proc(pid: int, task: str) -> ListedProcess:
    return ListedProcess(pid=pid, start="Fri Nov  6 10:00:%02d 2026" % (pid % 60), task_id=task,
                         started_at=NOW, children=1, summary="until ! pgrep -f x; do sleep 5; done")


GONE, LIVE, PARENT = _proc(101, "b1"), _proc(102, "b2"), _proc(103, "b3")
LISTED = [GONE, LIVE, PARENT]
OWNERS = {"b1": "agent-done", "b2": "agent-live"}


def test_pure_detection_and_marks():
    assert lo.leftover_task_ids(["b1", "b2", "b3"], OWNERS, frozenset({"agent-done"})) == {"b1"}
    marks = lo.owner_finished_by_pid(LISTED, OWNERS, True, frozenset({"agent-done"}))
    assert marks == {101: True, 102: False, 103: False}
    assert lo.leftover_count(marks) == 1


def test_unmeasured_is_null_never_a_fake_zero():
    assert lo.leftover_count(lo.owner_finished_by_pid(LISTED, OWNERS, False, None)) is None
    assert lo.leftover_count(lo.owner_finished_by_pid(LISTED, OWNERS, True, None)) is None
    assert lo.leftover_count({}) == 0


def test_plan_stop_refuses_a_pid_that_is_not_a_leftover():
    marks = lo.owner_finished_by_pid(LISTED, OWNERS, True, frozenset({"agent-done"}))
    plan = lo.plan_stop(LISTED, marks, [(GONE.pid, GONE.start), (LIVE.pid, LIVE.start),
                                         (GONE.pid + 900, "x"), (GONE.pid, "wrong start")])
    assert plan.targets == [(GONE.pid, GONE.start)]
    assert [(r.pid, r.code) for r in plan.refused] == [
        (102, lo.REFUSE_NOT_LEFTOVER), (1001, lo.REFUSE_NOT_LEFTOVER), (101, lo.REFUSE_NOT_LEFTOVER)]
    assert lo.plan_stop(LISTED, marks, None).targets == [(GONE.pid, GONE.start)]


def _launch(task: str, agent: str) -> OpenLaunch:
    return OpenLaunch(agent_id=agent, kind=KIND_SHELL, task_id=task, launched_at=NOW - timedelta(hours=3))


def test_reader_names_live_shells_of_finished_owners(monkeypatch):
    from src.core.background_work import open_count
    monkeypatch.setattr(open_count, "conversation_launches",
                        lambda path: [(_launch("b1", "agent-done"), False), (_launch("b2", "agent-live"), False)])
    asked = []
    monkeypatch.setattr(open_count, "finished_agent_ids",
                        lambda path, ids, **kw: asked.append(sorted(ids)) or frozenset({"agent-done"}))
    reader = BackgroundCountReader(stdout_of=lambda pid: "/t/tasks/%s.output" % {11: "b1", 12: "b2"}[pid])
    args = dict(claude_pid=1, process_parents={11: 1, 12: 1}, process_started_at=None, now=NOW)
    assert reader.read_leftovers(Path("/x/u.jsonl"), **args) == frozenset({"b1"})
    assert asked == [["agent-done", "agent-live"]]
    monkeypatch.setattr(open_count, "finished_agent_ids", lambda path, ids, **kw: None)
    assert reader.read_leftovers(Path("/x/u.jsonl"), **args) is None
    assert reader.read_leftovers(None, **args) is None


def _row_with(leftovers):
    evidence = SimpleNamespace(background_process=BackgroundMeasure(STATE_RUNNING, 7),
                               background_leftovers=leftovers)
    return evidence


def test_listing_carries_the_leftover_count_or_null(monkeypatch):
    from src.api import parked_work_listing as pwl
    for leftovers, expect in ((frozenset({"a", "b"}), 2), (frozenset(), 0), (None, None)):
        monkeypatch.setattr(pwl, "fresh_claude_observation",
                            lambda w, i, n, ev=_row_with(leftovers): SimpleNamespace(evidence=ev))
        assert background_processes_for(None, None, NOW).leftover == expect


class _Manager:
    async def get_session_info(self, session_id=None):
        return SimpleNamespace(agent_family="claude", tmux_session="t", session=None) if session_id == "ses_x" else None

    def tmux_socket_name(self) -> str:
        return "test-socket"

    def claude_uuid_for_tmux_name(self, name):
        return None


def _client(monkeypatch, finished):
    reached = []
    monkeypatch.setattr(routes.bw_tree, "measure", lambda name, socket: SimpleNamespace(agent_pid=7))
    monkeypatch.setattr(routes, "list_processes", lambda tree: list(LISTED))

    async def owners(*a):
        return LaunchOwners("ok", dict(OWNERS))

    async def marks(*a):
        return lo.owner_finished_by_pid(LISTED, OWNERS, True, finished)

    monkeypatch.setattr(routes, "_owners", owners)
    monkeypatch.setattr(routes, "_owner_marks", marks)
    monkeypatch.setattr(routes, "guarded_terminate_all",
                        lambda name, socket, targets: (reached.append(list(targets)) or ([], None)))
    from src.api.auth import require_auth
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = _Manager()
    return TestClient(app), reached


def test_stop_route_refuses_a_pid_outside_the_leftover_set_and_signals_only_leftovers(monkeypatch):
    client, reached = _client(monkeypatch, frozenset({"agent-done"}))
    url = "/api/v1/sessions/ses_x/background-work/stop-leftovers"
    answer = client.post(url, json={"targets": [{"pid": LIVE.pid, "start": LIVE.start},
                                                {"pid": GONE.pid, "start": GONE.start}]})
    assert answer.status_code == 200, answer.text
    results = {r["pid"]: r for r in answer.json()["results"]}
    assert results[LIVE.pid]["outcome"] == "refused" and results[LIVE.pid]["code"] == "not_leftover"
    assert reached == [[(GONE.pid, GONE.start)]]
    reached.clear()
    client.post(url)
    assert reached == [[(GONE.pid, GONE.start)]]


def test_stop_route_with_unmeasured_owners_stops_nothing(monkeypatch):
    client, reached = _client(monkeypatch, None)
    client.post("/api/v1/sessions/ses_x/background-work/stop-leftovers")
    assert reached == []
