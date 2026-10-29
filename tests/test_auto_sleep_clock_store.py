
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_autosleep_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_autosleep_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config.auto_sleep import AUTO_SLEEP_KEY, AutoSleepConfig
from src.core.auto_sleep import store
from src.core.auto_sleep.idle_clock import IdleClock
from src.core.auto_sleep.idle_seed import SOURCE_CLAUDE_TRANSCRIPT, SeedResult

T0 = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)




def test_a_run_is_measured_from_the_first_idle_observation():
    clock = IdleClock()
    clock.observe("s1", "k@1", "idle", None, _at(0))
    clock.observe("s1", "k@1", "idle", None, _at(30))
    assert clock.idle_seconds("s1", _at(61)) == pytest.approx(61 * 60)


@pytest.mark.parametrize(
    "status",
    ["working", "working_subagent", "question", "notice", "finished_unread",
     "unknown", "dead"],
)
def test_every_other_status_resets_the_clock(status):
    clock = IdleClock()
    clock.observe("s1", "k@1", "idle", None, _at(0))
    clock.observe("s1", "k@1", status, None, _at(50))
    assert clock.idle_seconds("s1", _at(70)) is None
    clock.observe("s1", "k@1", "idle", None, _at(55))
    assert clock.idle_seconds("s1", _at(70)) == pytest.approx(15 * 60)


def test_a_hint_means_not_idle():
    clock = IdleClock()
    clock.observe("s1", "k@1", "idle", None, _at(0))
    clock.observe("s1", "k@1", "idle", "shell", _at(10))
    assert clock.idle_seconds("s1", _at(90)) is None


def test_a_new_instance_key_starts_a_new_run():
    clock = IdleClock()
    clock.observe("s1", "k@1", "idle", None, _at(0))
    clock.observe("s1", "k@2", "idle", None, _at(40))
    assert clock.idle_seconds("s1", _at(60)) == pytest.approx(20 * 60)




def test_the_first_idle_observation_is_seeded_from_the_injected_thunk():
    clock = IdleClock()
    seeded_since = _at(-600)
    calls = []

    def seed() -> SeedResult:
        calls.append(1)
        return SeedResult(since=seeded_since, source=SOURCE_CLAUDE_TRANSCRIPT)

    clock.observe("s1", "k@1", "idle", None, _at(0), seed=seed)
    assert len(calls) == 1
    assert clock.idle_seconds("s1", _at(0)) == pytest.approx(600 * 60)


def test_the_thunk_is_never_called_when_display_is_not_idle():
    clock = IdleClock()
    calls = []

    def seed() -> SeedResult:
        calls.append(1)
        return SeedResult(since=_at(-600), source=SOURCE_CLAUDE_TRANSCRIPT)

    clock.observe("s1", "k@1", "working", None, _at(0), seed=seed)
    assert calls == []


def test_a_second_idle_observation_of_the_same_run_never_reseeds():
    clock = IdleClock()
    calls = []

    def seed() -> SeedResult:
        calls.append(1)
        return SeedResult(since=_at(-600), source=SOURCE_CLAUDE_TRANSCRIPT)

    clock.observe("s1", "k@1", "idle", None, _at(0), seed=seed)
    clock.observe("s1", "k@1", "idle", None, _at(10), seed=seed)
    clock.observe("s1", "k@1", "idle", None, _at(20), seed=seed)
    assert len(calls) == 1


def test_a_non_idle_status_still_resets_the_clock_and_the_new_run_is_not_reseeded():
    clock = IdleClock()
    calls = []

    def seed() -> SeedResult:
        calls.append(1)
        return SeedResult(since=_at(-600), source=SOURCE_CLAUDE_TRANSCRIPT)

    clock.observe("s1", "k@1", "idle", None, _at(0), seed=seed)
    clock.observe("s1", "k@1", "working", None, _at(50), seed=seed)
    assert clock.idle_seconds("s1", _at(70)) is None
    clock.observe("s1", "k@1", "idle", None, _at(55), seed=seed)
    assert len(calls) == 1
    assert clock.idle_seconds("s1", _at(70)) == pytest.approx(15 * 60)


def test_no_seed_thunk_behaves_exactly_as_before():
    clock = IdleClock()
    clock.observe("s1", "k@1", "idle", None, _at(0))
    assert clock.idle_seconds("s1", _at(30)) == pytest.approx(30 * 60)


def test_a_seed_thunk_that_raises_falls_back_to_observed_at():
    clock = IdleClock()

    def seed() -> SeedResult:
        raise OSError("disk went away")

    clock.observe("s1", "k@1", "idle", None, _at(0), seed=seed)
    assert clock.idle_seconds("s1", _at(30)) == pytest.approx(30 * 60)


def test_prune_and_forget():
    clock = IdleClock()
    clock.observe("s1", "k@1", "idle", None, _at(0))
    clock.observe("s2", "k@2", "idle", None, _at(0))
    clock.prune({"s2"})
    assert clock.idle_ids() == ["s2"]
    clock.forget("s2")
    assert clock.idle_ids() == []




def test_the_wiring_passes_the_registry_shell_hint():
    import inspect

    from src.core.attention import wiring_builders

    source = inspect.getsource(wiring_builders.make_on_observation)
    assert "idle_clock.observe(" in source
    assert "activity_hint_for(observation.evidence.registry)" in source




@pytest.fixture()
def config_path(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"other": {"kept": True}}))
    return path


def test_absent_block_is_the_owners_default(config_path):
    got = store.read(config_path)
    assert got.enabled is True and got.idle_minutes == 60 and got.keep_awake == []


def test_unparseable_block_reads_as_default(config_path):
    config_path.write_text(json.dumps({AUTO_SLEEP_KEY: {"idle_minutes": "soon"}}))
    assert store.read(config_path) == AutoSleepConfig()


def test_set_settings_merges_and_keeps_other_blocks(config_path):
    status, got = store.set_settings(config_path, enabled=False, idle_minutes=45)
    assert got.enabled is False and got.idle_minutes == 45
    doc = json.loads(config_path.read_text())
    assert doc["other"] == {"kept": True}
    assert doc[AUTO_SLEEP_KEY]["idle_minutes"] == 45


def test_minutes_out_of_range_write_nothing(config_path):
    before = config_path.read_text()
    with pytest.raises(ValueError):
        store.set_settings(config_path, idle_minutes=1)
    assert config_path.read_text() == before


def test_a_stored_block_that_will_not_parse_is_not_overwritten(config_path):
    config_path.write_text(json.dumps({AUTO_SLEEP_KEY: {"enabled": "maybe"}}))
    before = config_path.read_text()
    with pytest.raises(store.StoredBlockInvalid):
        store.set_settings(config_path, enabled=True)
    assert config_path.read_text() == before


def test_keep_awake_adds_once_and_removes(config_path):
    store.set_keep_awake(config_path, "uuid-a", True)
    store.set_keep_awake(config_path, "uuid-a", True)
    _status, got = store.set_keep_awake(config_path, "uuid-b", True)
    assert got.keep_awake == ["uuid-a", "uuid-b"]
    _status, got = store.set_keep_awake(config_path, "uuid-a", False)
    assert got.keep_awake == ["uuid-b"]


def test_keep_awake_refuses_a_value_that_is_not_a_uuid(config_path):
    with pytest.raises(ValueError):
        store.set_keep_awake(config_path, 'x" onload="1', True)




def test_an_unread_observation_keeps_the_run_and_marks_it_unread():
    clock = IdleClock()
    clock.observe("s1", "k@1", "idle", None, _at(0), unread=True)
    clock.observe("s1", "k@1", "idle", None, _at(30), unread=True)
    assert clock.is_unread("s1") is True
    assert clock.sleep_seconds("s1", _at(61), unread=True) == pytest.approx(61 * 60)


def test_reading_an_unread_run_restarts_only_the_read_measure():
    clock = IdleClock()
    clock.observe("s1", "k@1", "idle", None, _at(0), unread=True)
    clock.observe("s1", "k@1", "idle", None, _at(100), unread=False)
    assert clock.is_unread("s1") is False
    assert clock.sleep_seconds("s1", _at(110), unread=False) == pytest.approx(10 * 60)
    assert clock.sleep_seconds("s1", _at(110), unread=True) == pytest.approx(110 * 60)


def test_a_never_unread_run_is_measured_from_its_start():
    clock = IdleClock()
    clock.observe("s1", "k@1", "idle", None, _at(0))
    assert clock.sleep_seconds("s1", _at(61), unread=False) == pytest.approx(61 * 60)


def test_the_watcher_feeds_the_clock_without_the_unread_overlay():
    import inspect

    from src.core.attention import wiring_builders

    source = inspect.getsource(wiring_builders.make_on_observation)
    assert "unread=False, tmux_status=STATUS_UNKNOWN" in source
    assert "unread=unread," in source
