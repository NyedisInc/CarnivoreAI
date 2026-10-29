from __future__ import annotations

import pytest

from src.core.automations import models as m
from src.core.automations import run_feed, targets
from src.core.automations.run_title import build
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for

NOW = 1_800_000_000.0


def test_shapes() -> None:
    cases = [
        (dict(status=m.SUCCEEDED, kind="command", report={"command": "ls", "exit_code": 0, "duration_s": 1.5}, output_empty=True),
         "nightly found nothing", "finished with nothing to report"),
        (dict(status=m.SUCCEEDED, kind="command", report={"command": "ls", "exit_code": 0, "duration_s": 1.5, "stdout": "x"},
              output_empty=False), "nightly finished", "the command exited with code 0 after 1.5 s"),
        (dict(status=m.SUCCEEDED, kind="agent", report={"final_text": "found 3 stale branches\nmore"}, output_empty=False),
         "nightly finished", "found 3 stale branches"),
        (dict(status=m.SUCCEEDED, kind="recipe", report={"projects": [1, 2, 3]}, output_empty=False),
         "nightly finished", "report with 3 items"),
        (dict(status=m.FAILED, reason="exit_2"), "nightly failed", "the command exited with code 2"),
        (dict(status=m.FAILED, reason="timeout"), "nightly failed", "it ran out of time"),
        (dict(status=m.FAILED), "nightly failed", "it failed"),
        (dict(status=m.SKIPPED, reason=m.R_MISSED), "nightly was skipped",
         "skipped because the computer was asleep or the app was off at the scheduled time"),
        (dict(status=m.WAITING), "nightly needs you", "waiting for you to continue it"),
        (dict(status=m.CANCELLED), "nightly was canceled", "canceled before it finished"),
        (dict(status=m.SUCCEEDED), "nightly finished", "finished"),
    ]
    for kwargs, title, summary in cases:
        assert build(name="nightly", **kwargs) == (title, summary)
    assert build(name="", status=m.FAILED)[0] == "this automation failed"
    assert chr(0x2014) not in build(name="a", status=m.SKIPPED, reason="x_y")[1]


@pytest.fixture(autouse=True)
def _runners(monkeypatch):
    async def runner(ctx, automation, run):
        return m.RunOutcome()
    for kind in m.TARGET_KINDS:
        monkeypatch.setitem(targets.RUNNERS, kind, runner)


def test_store_writes_and_serves(tmp_path) -> None:
    store = AutomationStore(storage_for(tmp_path), clock=lambda: NOW)
    auto = store.create(name="nightly", cron="0 3 * * *", target={"kind": "command", "command": "true"})
    aid = auto["automation_id"]
    run = store.insert_run(aid, "boot1")
    assert run["title"] is None and run["summary"] is None
    done = store.update_run(run["run_id"], status=m.FAILED, reason="exit_3", report={"command": "true", "exit_code": 3})
    assert (done["title"], done["summary"]) == ("nightly failed", "the command exited with code 3")
    live = store.insert_run(aid, "boot1")
    assert store.update_run(live["run_id"], status=m.RUNNING)["title"] is None
    store.update_run(live["run_id"], status=m.CANCELLED)
    skip = store.finish_skip(store.insert_run(aid, "boot1")["run_id"], m.R_DISABLED)
    assert store.run(skip)["title"] == "nightly was skipped"
    page = run_feed.feed(store, before="", limit=10, automation_ids=[], statuses=[], triggers=[], hosts=[], no_host=False,
                         counters=[], with_report=False)
    assert {r["run_id"]: r["title"] for r in page["runs"]}[done["run_id"]] == "nightly failed"
