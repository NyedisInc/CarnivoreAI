
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from src.core.session_token_usage.cache import IncrementalCache
from src.core.timers.contract import check_call, check_result
from src.core.timers.index import TimerIndex, read_timer_index
from src.core.timers.reader import (
    PROCESS_ALIVE,
    PROCESS_GONE,
    UNKNOWN_PROCESS,
    ProcessFact,
    derive_timers,
)
from tests.helpers.timer_fixture import Transcript, at

ALIVE_EARLY = ProcessFact(PROCESS_ALIVE, at(8, 0))
NOW = at(10, 5)


def _derive(transcript: Transcript, tmp_path: Path, process=ALIVE_EARLY, now=NOW):
    path = transcript.write(tmp_path)
    index = read_timer_index(path, cache=IncrementalCache())
    assert index is not None
    return derive_timers(index, process, now)


def _by_id(rows):
    return {row.id: row for row in rows}


def test_a_pending_wakeup_is_live_with_its_recorded_fire_time(tmp_path):
    t = Transcript()
    t.prompt(at(9, 0))
    t.wakeup(at(10, 0), "toolu_w1", delay=1800)
    rows, counts, upcoming = _derive(t, tmp_path)
    assert counts.live == 1 and counts.total == 1
    assert rows[0].status == "live" and rows[0].kind == "wakeup"
    assert rows[0].fire_at == "2026-09-27T10:30:00Z"
    assert upcoming == at(10, 30)


def test_a_newer_wakeup_supersedes_and_a_later_turn_fires(tmp_path):
    t = Transcript()
    t.wakeup(at(9, 0), "toolu_w1", delay=300)
    t.prompt(at(9, 5), meta=True)
    t.wakeup(at(9, 6), "toolu_w2", delay=600)
    rows, counts, _ = _derive(t, tmp_path)
    by = _by_id(rows)
    assert by["toolu_w1"].status == "superseded"
    assert by["toolu_w2"].status == "live"
    t.prompt(at(9, 16), meta=True)
    rows, counts, upcoming = _derive(t, tmp_path)
    assert _by_id(rows)["toolu_w2"].status == "fired"
    assert counts.live == 0 and upcoming is None


def test_a_turn_before_the_fire_time_does_not_fire_it(tmp_path):
    t = Transcript()
    t.wakeup(at(10, 0), "toolu_w1", delay=1800)
    t.prompt(at(10, 2))
    rows, _, _ = _derive(t, tmp_path)
    assert rows[0].status == "live"


def test_stop_true_cancels_the_loop(tmp_path):
    t = Transcript()
    t.wakeup(at(10, 0), "toolu_w1", delay=1800)
    t.wakeup(at(10, 1), "toolu_w2", delay=60, stop=True)
    rows, counts, _ = _derive(t, tmp_path)
    assert {row.status for row in rows} == {"cancelled"}
    assert counts.cancelled == 2 and counts.live == 0


def test_a_restarted_process_lost_its_timers(tmp_path):
    t = Transcript()
    t.wakeup(at(10, 0), "toolu_w1", delay=1800)
    t.cron(at(10, 0), "toolu_c1", "49759e95", "*/5 * * * *")
    rows, counts, upcoming = _derive(t, tmp_path, process=ProcessFact(PROCESS_ALIVE, at(10, 1)))
    assert counts.lost == 2 and counts.live == 0 and upcoming is None


def test_a_dead_process_has_no_live_timers(tmp_path):
    t = Transcript()
    t.wakeup(at(10, 0), "toolu_w1", delay=1800)
    _, counts, upcoming = _derive(t, tmp_path, process=ProcessFact(PROCESS_GONE))
    assert counts.lost == 1 and counts.live == 0 and upcoming is None


def test_an_unmeasured_process_is_unknown_never_live(tmp_path):
    t = Transcript()
    t.wakeup(at(10, 0), "toolu_w1", delay=1800)
    rows, counts, _ = _derive(t, tmp_path, process=UNKNOWN_PROCESS)
    assert rows[0].status == "unknown" and counts.live == 0 and counts.unknown == 1


def test_a_recurring_cron_is_live_with_a_next_fire_from_now(tmp_path):
    t = Transcript()
    t.cron(at(10, 0), "toolu_c1", "49759e95", "*/5 * * * *")
    rows, counts, upcoming = _derive(t, tmp_path, now=at(10, 7, 30))
    row = rows[0]
    assert row.id == "49759e95" and row.status == "live" and row.recurring is True
    assert row.human_schedule == "Every 5 minutes"
    assert row.expires_at == "2026-10-04T10:00:00Z"
    assert upcoming == at(10, 10)


def test_cron_delete_cancels_by_id(tmp_path):
    t = Transcript()
    t.cron(at(10, 0), "toolu_c1", "49759e95", "*/5 * * * *")
    t.cron(at(10, 1), "toolu_c2", "ef56ab78", "*/30 * * * *")
    t.cron_delete(at(10, 2), "toolu_d1", "49759e95")
    rows, counts, _ = _derive(t, tmp_path)
    by = _by_id(rows)
    assert by["49759e95"].status == "cancelled"
    assert by["ef56ab78"].status == "live"
    assert counts.cancelled == 1 and counts.live == 1


def test_a_recurring_cron_past_its_recorded_expiry_is_expired(tmp_path):
    t = Transcript()
    t.cron(at(10, 0), "toolu_c1", "49759e95", "*/5 * * * *", days=3)
    _, counts, _ = _derive(t, tmp_path, now=at(10, 0) + timedelta(days=3, minutes=1))
    assert counts.expired == 1 and counts.live == 0


def test_a_one_shot_cron_fires_once_a_turn_starts_after_it(tmp_path):
    t = Transcript()
    t.cron(at(10, 0), "toolu_c1", "49759e95", "30 * * * *", recurring=False)
    rows, _, upcoming = _derive(t, tmp_path)
    assert rows[0].status == "live" and upcoming is not None
    t.prompt(upcoming + timedelta(seconds=2), meta=True)
    rows, counts, _ = _derive(t, tmp_path)
    assert rows[0].status == "fired" and counts.live == 0


def test_a_pending_sleep_shell_is_live_with_its_derived_fire_time(tmp_path):
    t = Transcript()
    t.call(at(9, 30), "Bash", "toolu_s1",
           {"command": "sleep 3600 && ./check.sh", "run_in_background": True})
    rows, counts, upcoming = _derive(t, tmp_path)
    assert counts.live == 1 and counts.total == 1
    assert rows[0].kind == "sleep" and rows[0].status == "live"
    assert rows[0].fire_at == "2026-09-27T10:30:00Z"
    assert upcoming == at(10, 30)


def test_a_sleep_shell_fires_once_its_delay_elapses(tmp_path):
    t = Transcript()
    t.call(at(9, 0), "Bash", "toolu_s1",
           {"command": "sleep 300 && ./check.sh", "run_in_background": True})
    rows, counts, _ = _derive(t, tmp_path, now=at(9, 10))
    assert rows[0].status == "fired" and counts.fired == 1 and counts.live == 0


def test_a_foreground_sleep_is_not_a_timer(tmp_path):
    t = Transcript()
    t.call(at(9, 0), "Bash", "toolu_s1", {"command": "sleep 300 && ./check.sh"})
    rows, counts, _ = _derive(t, tmp_path)
    assert counts.total == 0


def test_a_non_sleep_background_shell_is_not_a_timer(tmp_path):
    t = Transcript()
    t.call(at(9, 0), "Bash", "toolu_s1",
           {"command": "python3 scripts/hud_server.py", "run_in_background": True})
    rows, counts, _ = _derive(t, tmp_path)
    assert counts.total == 0


def test_a_restarted_process_lost_its_sleep_timer(tmp_path):
    t = Transcript()
    t.call(at(9, 0), "Bash", "toolu_s1",
           {"command": "sleep 3600 && ./check.sh", "run_in_background": True})
    restarted = ProcessFact(PROCESS_ALIVE, at(9, 30))
    rows, counts, _ = _derive(t, tmp_path, process=restarted, now=at(9, 15))
    assert rows[0].status == "lost" and counts.lost == 1


def test_a_refused_call_scheduled_nothing(tmp_path):
    t = Transcript()
    t.call(at(10, 0), "ScheduleWakeup", "toolu_w1",
           {"delaySeconds": 60, "reason": "r", "prompt": "p"})
    t.result(at(10, 0), "toolu_w1", "The user doesn't want to proceed with this tool use.",
             "Error: refused")
    rows, counts, _ = _derive(t, tmp_path)
    assert rows[0].status == "refused" and counts.live == 0


def test_a_changed_shape_is_named_never_live(tmp_path):
    t = Transcript()
    t.call(at(10, 0), "ScheduleWakeup", "toolu_w1", {"delay": "soon", "prompt": "p"})
    t.cron(at(10, 1), "toolu_c1", "49759e95", "*/5 * * * *")
    t.records[-1]["toolUseResult"]["id"] = 12345678
    rows, counts, _ = _derive(t, tmp_path)
    assert counts.shape_unrecognized == 2 and counts.live == 0


def test_a_call_without_a_result_yet_fires_at_created_plus_delay(tmp_path):
    t = Transcript()
    t.wakeup(at(10, 0), "toolu_w1", delay=120, answer=False)
    rows, _, upcoming = _derive(t, tmp_path)
    assert rows[0].status == "live" and upcoming == at(10, 2)


def test_a_sidechain_call_is_not_this_conversations_timer(tmp_path):
    t = Transcript()
    t.wakeup(at(10, 0), "toolu_w1", delay=120)
    for record in t.records:
        record["isSidechain"] = True
    _, counts, _ = _derive(t, tmp_path)
    assert counts.total == 0


def test_prompt_summaries_are_redacted_and_truncated(tmp_path):
    key = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # synthetic test value, never issued
    t = Transcript()
    t.wakeup(at(10, 0), "toolu_w1", delay=60, prompt=f"use {key} then " + "x" * 400)
    rows, _, _ = _derive(t, tmp_path)
    assert key not in (rows[0].prompt or "")
    assert "[redacted]" in rows[0].prompt
    assert len(rows[0].prompt) <= 160 and rows[0].prompt.endswith("...")


def test_the_index_resumes_from_its_offset(tmp_path):
    cache = IncrementalCache()
    t = Transcript()
    t.wakeup(at(10, 0), "toolu_w1", delay=60)
    path = t.write(tmp_path)
    first = read_timer_index(path, cache=cache)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"torn": ')
    second = read_timer_index(path, cache=cache)
    assert [c.tool_use_id for c in second.calls] == [c.tool_use_id for c in first.calls]
    assert cache.knows(str(path.resolve())) or cache.knows(str(path))


def test_an_unreadable_transcript_is_none(tmp_path):
    assert read_timer_index(tmp_path / "missing.jsonl", cache=IncrementalCache()) is None


@pytest.mark.parametrize("tool,document,ok", [
    ("ScheduleWakeup", {"delaySeconds": 5, "prompt": "p", "reason": "r"}, True),
    ("ScheduleWakeup", {"delaySeconds": "5", "prompt": "p"}, False),
    ("CronCreate", {"cron": "* * * * *", "prompt": "p"}, True),
    ("CronDelete", {}, False),
])
def test_call_contracts(tool, document, ok):
    assert check_call(tool, document).recognized is ok


def test_result_contract_names_fields_only():
    check = check_result("ScheduleWakeup", {"scheduledFor": "secret-value"})
    assert not check.recognized
    assert "secret-value" not in " ".join(check.problems)


def test_an_empty_index_counts_zero():
    _, counts, upcoming = derive_timers(TimerIndex(), ALIVE_EARLY, NOW)
    assert counts.total == 0 and upcoming is None
