
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.core.app_alerts import constants as AK
from src.core.app_alerts import service
from src.core.backup_health import constants as HK
from src.core.backup_health import runner
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import follow, health, retention
from src.cplugs.save.vault.follow import Engine
from src.cplugs.sdk.blob_codec import Throttle
from tests.python.cplugs.save.vault_helpers import World, jsonl

NOW = 2_000_000_000.0


def _conv(i: int) -> str:
    return f"00000000-0000-4000-8000-{i:012d}"


def _engine(world: World, state, clock: dict) -> Engine:
    return Engine(lambda: world.vault, state, lambda: world.sources, throttle=Throttle(sleep=lambda s: None),
                  clock=lambda: clock["t"])


def _busy(engine: Engine) -> None:
    engine._drain = lambda vault, sources, now: (0, 0, 0)  # type: ignore[method-assign]
    engine._queue.append(("never-drained", "claude"))


def test_a_busy_queue_still_gets_a_protection_pass_within_the_timer(tmp_path, monkeypatch):
    world, clock, calls = World(tmp_path), {"t": 1_000_000.0}, []
    world.write_conversation(jsonl(20))
    monkeypatch.setattr(follow.retention, "assess", lambda *a, **kw: calls.append(kw["now"]))
    engine = _engine(world, world.state, clock)
    _busy(engine)
    engine.run_slice()
    calls.clear()
    clock["t"] += follow.PROTECTION_SECONDS - 1
    engine.run_slice()
    assert calls == []
    clock["t"] += 2
    engine.run_slice()
    assert len(calls) == 1 and engine._queue


def test_a_protection_pass_follows_a_full_sweep_whatever_the_queue_holds(tmp_path, monkeypatch):
    world, clock, calls = World(tmp_path), {"t": 1_000_000.0}, []
    world.write_conversation(jsonl(20))
    monkeypatch.setattr(follow.retention, "assess", lambda *a, **kw: calls.append(kw["now"]))
    engine = _engine(world, world.state, clock)
    _busy(engine)
    engine.run_slice()
    assert len(calls) == 1


def _vault_with_conversations(tmp_path, count: int) -> World:
    world = World(tmp_path)
    for i in range(count):
        world.write_conversation(jsonl(5, seed=i), conv=_conv(i), enc=f"-proj-{i}", subagents=0, tool_results=0)
        world.capture(conv=_conv(i))
    return world


def _lose(world: World, first: int, last: int) -> None:
    for i in range(first, last):
        world.transcript(_conv(i), f"-proj-{i}").unlink()


@pytest.mark.parametrize("lost, expected", [(10, 10), (9, None)])
def test_ten_originals_gone_in_the_window_report_a_mass_event_and_nine_do_not(tmp_path, lost, expected):
    assert K.MASS_GONE_THRESHOLD == 10
    world = _vault_with_conversations(tmp_path, 12)
    assert retention.assess(world.vault, now=NOW)["mass_gone"] is None
    _lose(world, 0, lost)
    report = retention.assess(world.vault, now=NOW + 60)["mass_gone"]
    assert (report and report["count"]) == expected
    if report:
        assert len(report["samples"]) == K.MASS_GONE_SAMPLES and all("-proj-" in s for s in report["samples"])
    assert world.vault.manifests.newest(_conv(0)) is not None


def test_a_vault_that_already_holds_gone_units_does_not_alarm_on_its_first_pass(tmp_path):
    world = _vault_with_conversations(tmp_path, 12)
    _lose(world, 0, 12)
    assert retention.assess(world.vault, now=NOW)["mass_gone"] is None


def test_units_gone_outside_the_window_are_not_added_together(tmp_path):
    world = _vault_with_conversations(tmp_path, 12)
    retention.assess(world.vault, now=NOW)
    _lose(world, 0, 6)
    assert retention.assess(world.vault, now=NOW + 60)["mass_gone"] is None
    _lose(world, 6, 12)
    assert retention.assess(world.vault, now=NOW + 2 * 3600)["mass_gone"] is None


@pytest.fixture()
def alerts(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    db = db_path_for(state)
    service.configure(db, None)
    yield SimpleNamespace(state=state, db=db, drive=tmp_path / "nodrive")
    service.configure(None, None)


def _mass_alerts(alerts) -> list:
    rows = service.list_view(alerts.db, include_closed=True, limit=100)["alerts"]
    return [r for r in rows if r["key"] == HK.KEY_VAULT_MASS_GONE]


def test_a_mass_event_raises_exactly_one_alert_that_stays_until_dismissed(alerts):
    record = dict(active=True, swept_at=NOW - 60, on_disk=40, uncovered=0, last_ok_at=NOW - 60, started_at=NOW - 3600,
                  unavailable="", over_cap=False, damaged=0, pending=0,
                  mass_gone={"count": 12, "samples": ["/a", "/b", "/c", "/d", "/e"], "at": NOW})
    path = alerts.state / "vault-health.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    for _ in range(2):
        runner.run_checks(alerts.state, alerts.db, now=NOW, volume=alerts.drive)
    rows = _mass_alerts(alerts)
    assert len(rows) == 1 and rows[0]["state"] == AK.STATE_ACTIVE
    assert rows[0]["params"] == {"count": 12, "samples": "/a, /b, /c, /d, /e"}
    path.write_text(json.dumps({**record, "mass_gone": None}), encoding="utf-8")
    runner.run_checks(alerts.state, alerts.db, now=NOW + 7200, volume=alerts.drive)
    assert _mass_alerts(alerts)[0]["state"] == AK.STATE_ACTIVE
    service.dismiss(alerts.db, rows[0]["id"])
    assert _mass_alerts(alerts)[0]["state"] == AK.STATE_DISMISSED


def _lose_and_check(tmp_path, alerts, lost: int) -> SimpleNamespace:
    world = _vault_with_conversations(tmp_path / "w", 12)
    clock = {"t": NOW}
    engine = _engine(world, alerts.state, clock)
    while engine.run_slice().more:
        pass
    _lose(world, 0, lost)
    clock["t"] += follow.PROTECTION_SECONDS + 1
    engine.run_slice()
    for _ in range(2):
        runner.run_checks(alerts.state, alerts.db, now=clock["t"], volume=alerts.drive)
    return SimpleNamespace(record=health.read(alerts.state), rows=_mass_alerts(alerts))


def test_nine_gone_raise_no_alert_end_to_end(tmp_path, alerts):
    out = _lose_and_check(tmp_path, alerts, 9)
    assert out.record["mass_gone"] is None and out.rows == []


def test_ten_gone_raise_one_alert_end_to_end(tmp_path, alerts):
    out = _lose_and_check(tmp_path, alerts, 10)
    assert out.record["mass_gone"]["count"] == 10 and len(out.rows) == 1


def test_a_unit_that_flaps_gone_and_back_counts_once(tmp_path):
    from src.cplugs.save.vault import gone_watch

    root = tmp_path
    units = {f"u{i}": f"/p/{i}" for i in range(6)}
    assert gone_watch.observe(root, {}, NOW) is None
    for step in range(1, 5):
        assert gone_watch.observe(root, units if step % 2 else {}, NOW + step * 60) is None


def test_units_the_owner_removed_on_purpose_are_remembered_but_not_counted(tmp_path):
    from src.cplugs.save.vault import gone_watch

    units = {f"u{i}": f"/p/{i}" for i in range(10)}
    gone_watch.observe(tmp_path, {}, NOW)
    assert gone_watch.observe(tmp_path, units, NOW + 60, intentional=frozenset(units)) is None
    assert gone_watch.observe(tmp_path, units, NOW + 120) is None


def test_the_event_gets_a_new_step_each_time_it_grows_by_a_full_threshold(tmp_path):
    from src.cplugs.save.vault import gone_watch

    gone_watch.observe(tmp_path, {}, NOW)
    steps = []
    for total in (10, 15, 19, 20, 29, 30):
        report = gone_watch.observe(tmp_path, {f"u{i}": f"/p/{i}" for i in range(total)}, NOW + total)
        steps.append((report["count"], report["step"]))
    assert steps == [(10, 0), (15, 0), (19, 0), (20, 1), (29, 1), (30, 2)]


def test_growth_after_a_dismissal_raises_a_fresh_alert(alerts):
    base = dict(active=True, swept_at=NOW - 60, on_disk=40, uncovered=0, last_ok_at=NOW - 60, started_at=NOW - 3600,
                unavailable="", over_cap=False, damaged=0, pending=0)
    path = alerts.state / "vault-health.json"

    def run(count: int, step: int):
        path.write_text(json.dumps({**base, "mass_gone": {"count": count, "samples": ["/a"], "at": NOW, "step": step}}), encoding="utf-8")
        runner.run_checks(alerts.state, alerts.db, now=NOW, volume=alerts.drive)

    run(10, 0)
    first = _mass_alerts(alerts)[0]
    service.dismiss(alerts.db, first["id"])
    run(10, 0)
    assert [r["state"] for r in _mass_alerts(alerts)] == [AK.STATE_DISMISSED]
    run(20, 1)
    states = sorted(r["state"] for r in _mass_alerts_any(alerts))
    assert states == [AK.STATE_ACTIVE, AK.STATE_DISMISSED]


def _mass_alerts_any(alerts) -> list:
    rows = service.list_view(alerts.db, include_closed=True, limit=100)["alerts"]
    return [r for r in rows if r["key"].startswith(HK.KEY_VAULT_MASS_GONE)]


def _moved_world(tmp_path):
    world = World(tmp_path)
    for i in range(10):
        world.write_conversation(jsonl(5, seed=i), conv=_conv(i), enc="-proj-moved", subagents=0, tool_results=0)
        world.capture(conv=_conv(i))
    clock = {"t": NOW}
    engine = _engine(world, world.state, clock)
    while engine.run_slice().more:
        pass
    return world, engine, clock


def _move_folder(world: World, clock: dict, engine: Engine, *, noted: bool) -> dict:
    from src.core.backup_health import vault_moves

    old = world.projects / "-proj-moved"
    if noted:
        vault_moves.note_moved(world.state, [str(old)], clock["t"])
    old.rename(world.projects / "-proj-renamed")
    clock["t"] += follow.PROTECTION_SECONDS + 1
    engine.run_slice()
    return health.read(world.state)


def test_moving_a_project_with_ten_conversations_raises_no_alert(tmp_path):
    world, engine, clock = _moved_world(tmp_path)
    assert _move_folder(world, clock, engine, noted=True)["mass_gone"] is None


def test_the_same_rename_without_the_note_is_a_mass_event(tmp_path):
    world, engine, clock = _moved_world(tmp_path)
    assert _move_folder(world, clock, engine, noted=False)["mass_gone"]["count"] == 10


def test_a_forced_sweep_every_slice_does_not_force_a_pass_every_slice(tmp_path, monkeypatch):
    world, clock, calls = World(tmp_path), {"t": 1_000_000.0}, []
    world.write_conversation(jsonl(20))
    monkeypatch.setattr(follow.retention, "assess", lambda *a, **kw: calls.append(kw["now"]))
    engine = _engine(world, world.state, clock)
    monkeypatch.setattr(engine, "_follow", lambda vault: False)
    for _ in range(5):
        engine.run_slice()
        clock["t"] += 60
    assert len(calls) == 1
