
from __future__ import annotations

from src.cplugs.huddle import progress
from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401

PROGRESS = "/api/v1/cplugs/huddle/progress"


def lines(client, item_id: int) -> list:
    return client.get(PROGRESS).json()["progress"].get(str(item_id), [])


def test_progress_needs_auth(setup):
    from fastapi.testclient import TestClient
    with TestClient(setup.app) as anonymous:
        assert anonymous.get(PROGRESS).status_code in (401, 403)


def test_a_report_shows_one_line_per_worker_and_pushes(client, setup):
    item = add(client, "12", "build it")
    setup.published.clear()
    ok, answer = call(setup.manager, "task_manager_progress_set", {"item": item, "phase": "running", "note": "  writing   the strip ", "worker": "web"}, raw=True)
    assert ok and answer["item_id"] == item and answer["ok"] is True
    assert setup.published == ["cplug.huddle.progress"]
    call(setup.manager, "task_manager_progress_set", {"item": item, "phase": "testing"}, raw=True)
    call(setup.manager, "task_manager_progress_set", {"item": item, "phase": "installing", "worker": "web"}, raw=True)
    rows = {r["worker"]: r for r in lines(client, item)}
    assert set(rows) == {"web", "main"}
    assert rows["web"]["phase"] == "installing" and rows["web"]["note"] == "" and rows["main"]["phase"] == "testing"
    assert rows["web"]["stale"] is False and rows["web"]["age_s"] < 5


def test_refusals_leave_the_lines_alone(client, setup):
    item = add(client, "12", "x")
    for bad in ({"item": item, "phase": "napping"}, {"item": item, "phase": "running", "note": "n" * 301},
                {"item": item, "phase": "running", "worker": "w" * 41}, {"item": 9999, "phase": "running"},
                {"item": item, "phase": "running", "extra": 1}):
        ok, _ = call(setup.manager, "task_manager_progress_set", bad, raw=True)
        assert not ok
    assert lines(client, item) == []
    for n in range(progress.MAX_WORKERS):
        assert call(setup.manager, "task_manager_progress_set", {"item": item, "phase": "running", "worker": f"w{n}"}, raw=True)[0]
    assert not call(setup.manager, "task_manager_progress_set", {"item": item, "phase": "running", "worker": "one too many"}, raw=True)[0]
    assert call(setup.manager, "task_manager_progress_set", {"item": item, "phase": "done", "worker": "w0"}, raw=True)[0]


def test_a_line_goes_stale_after_30_minutes_and_is_forgotten_later(client, setup, monkeypatch):
    item = add(client, "12", "slow")
    now = [1_000_000.0]
    monkeypatch.setattr(progress.time, "time", lambda: now[0])
    call(setup.manager, "task_manager_progress_set", {"item": item, "phase": "running", "note": "going"}, raw=True)
    now[0] += progress.STALE_AFTER_S - 1
    assert lines(client, item)[0]["stale"] is False
    now[0] += 1
    row = lines(client, item)[0]
    assert row["stale"] is True and row["age_s"] == progress.STALE_AFTER_S and row["phase"] == "running"
    call(setup.manager, "task_manager_progress_set", {"item": item, "phase": "testing"}, raw=True)
    assert lines(client, item)[0]["stale"] is False
    now[0] += progress.DROP_AFTER_S + 1
    assert lines(client, item) == []


def test_the_batch_progress_op_is_the_same_write(client, setup):
    a, b = add(client, "12", "a"), add(client, "12", "b")
    ops = [{"op": "progress", "item_id": a, "phase": "installing", "note": "carnivore-try", "worker": "orch"},
           {"op": "progress", "item_id": b, "phase": "bogus"},
           {"op": "progress", "item_id": b, "phase": "blocked", "note": "needs a yes"}]
    ok, body = call(setup.manager, "task_manager_batch_run", {"list_id": "12", "ops": ops}, raw=True)
    assert ok and body["applied"] == 2 and body["failed"] == 1 and body["results"][1]["ok"] is False
    assert lines(client, a)[0]["phase"] == "installing" and lines(client, b)[0]["phase"] == "blocked"


def test_a_restart_shows_nothing(client, setup):
    item = add(client, "12", "x")
    call(setup.manager, "task_manager_progress_set", {"item": item, "phase": "running"}, raw=True)
    progress.reset()
    assert lines(client, item) == []
