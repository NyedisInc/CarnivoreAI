
from __future__ import annotations

import asyncio
import json
import logging.handlers
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.core.automations import gates, scheduler_log, targets
from src.core.automations import models as m
from src.core.automations.scheduler import Scheduler
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.automations.targets import session_message
from tests.python.automations.test_session_message import TARGET, Ops, world  # noqa: F401


@pytest.fixture
def log(tmp_path):
    scheduler_log.LOG.configure(tmp_path / "logs", scheduler_log.LogSettings(max_mb=1, keep=2))
    yield scheduler_log.LOG
    scheduler_log.LOG.close()


def _events(log, automation_id=None):
    return [line["event"] for line in reversed(log.read(automation_id, 1000))]


def test_rotates_at_size_and_keeps_only_keep_files(log):
    for i in range(6000):
        log.write("skipped", automation_id="aut_x", reason="r" * 400, n=i)
    files = sorted(p.name for p in log.path.parent.iterdir())
    assert files == [scheduler_log.FILENAME, scheduler_log.FILENAME + ".1", scheduler_log.FILENAME + ".2"]
    assert all(p.stat().st_size <= 1024 * 1024 + 2048 for p in log.path.parent.iterdir())
    assert log.read(limit=1)[0]["n"] == 5999


def test_a_saved_setting_goes_through_the_config_writer_and_applies_live(log, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"other": 1}))
    scheduler_log.save_settings(config, scheduler_log.LogSettings(rotate="daily", keep=7))
    stored = json.loads(config.read_text())
    assert stored["other"] == 1 and stored[scheduler_log.CONFIG_KEY] == {"rotate": "daily", "max_mb": 10, "keep": 7}
    assert isinstance(log._handler, logging.handlers.TimedRotatingFileHandler) and log._handler.backupCount == 7
    log.write("finished", automation_id="aut_x")
    assert _events(log) == ["finished"]
    assert scheduler_log.read_settings({scheduler_log.CONFIG_KEY: {"rotate": "hourly"}}) == scheduler_log.LogSettings()


def test_secrets_texts_and_output_never_reach_the_file(log):
    key = "sk-ant-api03-" + "C" * 90
    log.write("failed", automation_id="aut_x", error=f"boom {key}", text="the owner's message", argv=["/bin/x", key],
              report={"stdout_tail": key}, actor={"kind": "mcp", "token": key})
    raw = log.path.read_text()
    assert key not in raw and "the owner's message" not in raw and "argv" not in raw and "stdout_tail" not in raw
    with pytest.raises(ValueError):
        log.write("not_an_event")


def test_every_scheduler_event_is_written(log, world, monkeypatch):  # noqa: F811
    store = world.store
    outcomes = iter([m.RunOutcome(status=m.FAILED, reason="boom"), m.RunOutcome(status=m.SUCCEEDED)])

    async def runner(ctx, automation, run):
        return next(outcomes)

    monkeypatch.setitem(targets.RUNNERS, "recipe", runner)
    verdicts = iter([(None, {}), (None, {}), (gates.Verdict(m.SKIPPED, m.R_USAGE), {})])
    monkeypatch.setattr(gates, "evaluate", lambda *a: next(verdicts))
    action = {"kind": "recipe", "recipe": "sleep_idle_sessions"}
    auto = store.create(name="log", cron="*/15 * * * *", target=action, retry_max=1, retry_backoff_s=60)
    store.update(auto["automation_id"], None, description="d")

    async def go():
        sched = Scheduler(SimpleNamespace(), store)
        for _ in range(3):
            await sched.run_now(auto["automation_id"])
            await asyncio.gather(*sched._tasks)

    asyncio.run(go())
    slot = store.get(auto["automation_id"])["next_fire_at"]
    store.claim_due(slot + 3600, "boot")
    world.busy = 1
    msg = store.create(name="msg", cron="0 7 * * 1", target=TARGET)
    world.ops = Ops("live")
    run = store.insert_run(msg["automation_id"], "boot")
    ctx = SimpleNamespace(app_state=SimpleNamespace(), store=store, boot_id="boot")
    assert asyncio.run(session_message.run(ctx, msg, run)).status == m.SUCCEEDED
    store.delete(auto["automation_id"])
    seen = set(_events(log))
    assert seen >= set(scheduler_log.EVENTS) - {"claimed"}
    store.claim_due(store.get(msg["automation_id"])["next_fire_at"] + 1, "boot")
    assert "claimed" in _events(log, msg["automation_id"])
