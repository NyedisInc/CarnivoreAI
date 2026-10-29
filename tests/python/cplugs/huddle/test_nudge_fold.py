
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

from src.cplugs.host import plugin_fold, runtime, state as owner_state
from src.cplugs.huddle.nudge import scheduler, settings, sweep
from tests.python.cplugs.huddle.test_task_manager_nudge_sweep import Rig, rig  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401

SWEEP_BOUND_S = 30


def store_old_nudge(host, enabled: bool, saved: dict) -> None:
    path = owner_state.state_path(host.state_dir)
    document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"cplugs": {}}
    document.setdefault("cplugs", {})["nudge"] = {"enabled": enabled, "grants": [], "settings": saved, "revision": 3}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def huddle_settings(host) -> dict:
    return dict(owner_state.get(host.state_dir, runtime.find("huddle").manifest).settings)


def test_there_is_no_nudge_plugin_and_the_old_id_resolves_to_the_task_manager(app):
    assert runtime.find("nudge") is None
    huddle = runtime.find("huddle")
    assert runtime.legacy_target("nudge") is huddle and huddle.manifest.legacy_ids == {"nudge": settings.ENABLED}
    assert "nudge" not in [d.id for d in runtime.definitions()]


def test_the_nudge_ships_off_inside_a_task_manager_that_ships_on(app):
    host = runtime.host_for(app)
    assert host.enabled("huddle") is True
    assert settings.read(host.context("huddle").settings_now()).enabled is False
    assert settings.default(settings.ENABLED) is False


def test_every_setting_keeps_its_key_in_the_task_manager_manifest(app):
    fields = runtime.find("huddle").manifest.settings_schema["fields"]
    assert {"nudgeEnabled", "nudgeMinutes", "nudgeTries", "nudgeMaxItems", "unclaimedText", "pickupText", "claimedText"} <= set(fields)
    assert (fields["nudgeMinutes"]["default"], fields["nudgeTries"]["default"], fields["nudgeMaxItems"]["default"]) == (60, 3, 5)


def test_on_starts_the_scheduler_and_it_sweeps_and_off_stops_it(client, rig, monkeypatch):
    item = rig.add(client)
    rig.switch(client)
    real_sweep = sweep.sweep

    async def scenario():
        swept = asyncio.Event()

        async def signalling_sweep(*args, **kwargs):
            try:
                return await real_sweep(*args, **kwargs)
            finally:
                swept.set()

        monkeypatch.setattr(sweep, "sweep", signalling_sweep)
        scheduler.start(rig.nudge_ctx, clock=lambda: rig.later(1.5))
        try:
            assert scheduler.Running.task is not None and not scheduler.Running.task.done()
            await asyncio.wait_for(swept.wait(), SWEEP_BOUND_S)
        finally:
            scheduler.stop()
        assert scheduler.Running.task is None and scheduler.Running.unsubscribe == []

    asyncio.run(scenario())
    assert len(rig.pasted) == 1 and rig.item(item["id"])["nudge"]["count"] == 1


def test_saving_the_settings_wakes_the_sleeping_scheduler(rig):
    host = rig.host
    host._started.add("huddle")

    async def scenario():
        scheduler.start(rig.nudge_ctx)
        try:
            await asyncio.sleep(0.05)
            poked = asyncio.Event()
            scheduler.Running.scheduler.poke = poked.set
            await host.settings_saved("huddle")
            await asyncio.wait_for(poked.wait(), 1.0)
        finally:
            scheduler.stop()

    asyncio.run(scenario())


def test_the_fold_carries_the_old_switch_and_settings_once_and_never_deletes_them(app):
    host = runtime.host_for(app)
    huddle = runtime.find("huddle").manifest
    owner_state.update(host.state_dir, huddle, None, lambda st: replace(st, settings={"nudgeMinutes": 30, "nudgeTries": 5}))
    store_old_nudge(host, True, {"nudgeTries": 2, "claimedText": "custom {minutes}", "junk": 1})
    assert plugin_fold.migrate(host.state_dir) == {"huddle": {"nudgeTries": 2, "claimedText": "custom {minutes}", "nudgeEnabled": True}}
    assert huddle_settings(host) == {"nudgeMinutes": 30, "nudgeTries": 2, "claimedText": "custom {minutes}", "nudgeEnabled": True}
    assert owner_state.stored_entry(host.state_dir, "nudge")["settings"]["nudgeTries"] == 2
    owner_state.update(host.state_dir, huddle, None, lambda st: replace(st, settings={**st.settings, "nudgeEnabled": False, "nudgeTries": 7}))
    assert plugin_fold.migrate(host.state_dir) == {}
    assert huddle_settings(host)["nudgeEnabled"] is False and huddle_settings(host)["nudgeTries"] == 7


def test_a_nudge_that_was_off_stays_off_and_no_entry_moves_nothing(app):
    host = runtime.host_for(app)
    assert plugin_fold.migrate(host.state_dir) == {}
    store_old_nudge(host, False, {})
    plugin_fold.migrate(host.state_dir)
    assert huddle_settings(host) == {"nudgeEnabled": False}
    assert runtime.host_for(app).enabled("huddle") is True
