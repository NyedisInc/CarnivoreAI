
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.api import automation_timers_listing as listing
from src.core.automations import models as m
from src.core.automations import targets
from src.core.automations import timer_status as ts
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.models import SessionInfo

ON = {"automation_id": "a", "enabled": True, "retry_due_at": None}


@pytest.mark.parametrize("run,retry,word", [
    (None, None, "ok"), ({"status": "succeeded"}, None, "ok"),
    ({"status": "failed"}, None, "error"), ({"status": "failed"}, 123.0, "warning"),
    ({"status": "skipped"}, None, "warning"), ({"status": "cancelled"}, None, "warning"),
    ({"status": "waiting_on_you"}, None, "warning"),
])
def test_one_automation_word(run, retry, word):
    assert ts.automation_state({**ON, "retry_due_at": retry}, run) == word


def test_set_roll_up_is_worst_of_the_switched_on_ones():
    off = {"automation_id": "o", "enabled": False, "retry_due_at": None}
    failed, fine = {"status": "failed"}, {"status": "succeeded"}
    assert ts.roll_up([]) == ts.TimerStatus("none", 0, 0)
    assert ts.roll_up([(off, failed)]) == ts.TimerStatus("disabled", 1, 0)
    assert ts.roll_up([(ON, fine), (off, failed)]) == ts.TimerStatus("ok", 2, 1)
    assert ts.roll_up([(ON, fine), ({**ON, "automation_id": "b"}, {"status": "skipped"})]).state == "warning"
    assert ts.roll_up([(ON, {"status": "skipped"}), ({**ON, "automation_id": "b"}, failed)]).state == "error"


@pytest.fixture
def store(tmp_path, monkeypatch):
    for kind in m.TARGET_KINDS:
        monkeypatch.setitem(targets.RUNNERS, kind, lambda *a, **k: None)
    return AutomationStore(storage_for(tmp_path), notify=lambda topic: None)


def _make(store, name):
    return store.create(name=name, cron="0 7 * * 1", target={"kind": "recipe", "recipe": "scrooge"})["automation_id"]


def test_latest_stopped_run_skips_a_run_in_flight(store):
    a, b = _make(store, "one"), _make(store, "two")
    first = store.insert_run(a, "boot")
    store.update_run(first["run_id"], status="failed", reason="x", ended_at=1.0)
    second = store.insert_run(a, "boot")
    runs = store.latest_stopped_runs()
    assert runs[a]["run_id"] == first["run_id"] and second["status"] == "claimed"
    assert b not in runs


def test_marker_stamps_the_right_row_and_none_elsewhere(store, monkeypatch):
    a = _make(store, "one")
    monkeypatch.setattr(store, "list_all", lambda: [{"automation_id": a, "enabled": True, "retry_due_at": None,
                                                     "target": {"kind": "session_message", "session_uuid": "u1"}}])
    run = store.insert_run(a, "boot")
    store.update_run(run["run_id"], status="failed", reason="x", ended_at=1.0)
    monkeypatch.setattr(listing, "_row_ids", lambda uuids: {"u1": 7})

    def row(row_id):
        return SessionInfo.model_construct(host_key="local", origin_install_id=None, session_row_id=row_id,
                                           session=SimpleNamespace(id="ses_x"), automations_state="stale")

    mine, other = row(7), row(8)
    asyncio.run(listing.mark_automation_timers(SimpleNamespace(automation_store=store), [mine, other]))
    assert (mine.automations_state, mine.automations_total, mine.automations_enabled) == ("error", 1, 1)
    assert (other.automations_state, other.automations_total) == ("none", 0)


def test_unreadable_store_is_null_not_none():
    info = SessionInfo.model_construct(host_key="local", origin_install_id=None, session_row_id=1,
                                       session=SimpleNamespace(id="ses_x"), automations_state="ok",
                                       automations_total=1, automations_enabled=1)
    asyncio.run(listing.mark_automation_timers(SimpleNamespace(), [info]))
    assert (info.automations_state, info.automations_total, info.automations_enabled) == (None, None, None)


def test_global_word_reads_disabled_while_paused(store):
    _make(store, "one")
    assert listing.global_status(store, False) == {"state": "ok", "total": 1, "enabled": 1}
    assert listing.global_status(store, True)["state"] == "disabled"
    assert listing.global_status(store, True) != listing.global_status(store, False)
    assert m.FAILED == "failed"
