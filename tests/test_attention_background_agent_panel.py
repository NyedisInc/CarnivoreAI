
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from src.core.attention.display import to_display
from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_SUBAGENTS,
    STATE_BUSY,
    Evidence,
)
from src.core.attention.pane_markers import (
    RESTING_PROMPT_MARKER,
    RESTING_TAIL_LINES,
    classify_pane_tail,
    detect_resting_prompt,
)
from src.core.attention.pane_prompt_box import line_above_prompt_box
from src.core.attention.registry_record import parse_registry_record
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import FACTS_FOUND, TranscriptFacts
from src.core.session_status import (
    LIVENESS_LIVE,
    STATUS_UNKNOWN,
    STATUS_WORKING_SUBAGENT,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "agent_captures"
    / "claude_background_agents_panel.txt"
)
NOW = datetime(2026, 9, 25, 10, 58, 0, tzinfo=timezone.utc)
SHELL_PILL = " · 1 shell"
WAITING = "✻ Waiting for 3 background agents to finish"
TURN_END = "✻ Cooked for 2m 3s · done 7:01 AM"


def _capture() -> List[str]:
    return FIXTURE.read_text(encoding="utf-8").splitlines()


def _without_shell_pill(lines: List[str]) -> List[str]:
    return [line.replace(SHELL_PILL, "") for line in lines]


def _with_panel_rows(lines: List[str], extra: int) -> List[str]:
    last = max(i for i, line in enumerate(lines) if "◯ worker" in line)
    rows = [
        "  ◯ worker  Extra background task %d        1m 2s · ↓ 1.0k tokens" % n
        for n in range(extra)
    ]
    return lines[: last + 1] + rows + lines[last + 1 :]


def _evidence(pane_lines: List[str], *, pending: int) -> Evidence:
    registry = parse_registry_record(
        {
            "pid": 3257,
            "sessionId": "2629dba5-234e-44d2-be54-ddaf69c8db4b",
            "cwd": "/Users/user/Development/CloudeCode",
            "startedAt": 1790285280725,
            "version": "2.1.282",
            "kind": "interactive",
            "entrypoint": "cli",
            "tmux": "carnivore_Agent_-_Cloude_Code:@4.%4",
            "status": "busy",
            "updatedAt": int(NOW.timestamp() * 1000) - 60_000,
            "statusUpdatedAt": int(NOW.timestamp() * 1000) - 60_000,
        },
        path_pid=None,
    )
    end = NOW - timedelta(seconds=240)
    facts = TranscriptFacts(
        verdict=FACTS_FOUND,
        pending_background_agents=pending,
        pending_field_present=True,
        turn_end_at=end,
        newest_assistant_at=end - timedelta(seconds=1),
        newest_append_at=end,
        detail="the turn ended with %d background agents pending" % pending,
    )
    pane = classify_pane_tail(pane_lines)
    return Evidence(
        tmux_liveness=LIVENESS_LIVE,
        agent_family=FAMILY_CLAUDE,
        registry=registry,
        transcript=facts,
        pane=pane,
        resting_prompt_held=pane.resting_prompt is True,
        now=NOW,
    )


def test_the_live_capture_is_not_resting():
    assert detect_resting_prompt(_capture()) is False
    assert detect_resting_prompt(_without_shell_pill(_capture())) is False


def test_a_tall_agent_panel_no_longer_hides_the_waiting_line():
    tall = _with_panel_rows(_without_shell_pill(_capture()), 3)
    window = "\n".join(tall[-RESTING_TAIL_LINES * 2 :])
    assert WAITING in "\n".join(tall)
    nonblank = [line for line in tall if line.strip()]
    assert WAITING not in nonblank[-RESTING_TAIL_LINES:], window
    assert detect_resting_prompt(tall) is False


def test_a_multi_line_typed_prompt_does_not_hide_it_either():
    lines = _without_shell_pill(_capture())
    box = next(i for i, line in enumerate(lines) if line.startswith("❯"))
    typed = ["  continued line %d of a long question" % n for n in range(4)]
    lines = lines[: box + 1] + typed + lines[box + 1 :]
    assert detect_resting_prompt(lines) is False


def test_the_tall_panel_resolves_working_subagent_end_to_end():
    tall = _with_panel_rows(_without_shell_pill(_capture()), 3)
    verdict = resolve_attention(_evidence(tall, pending=3))
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS), verdict.detail
    display = to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN)
    assert display == STATUS_WORKING_SUBAGENT


def test_finished_agents_do_not_keep_it_working():
    done = [TURN_END if line == WAITING else line for line in _without_shell_pill(_capture())]
    assert detect_resting_prompt(done) is True
    assert detect_resting_prompt(_with_panel_rows(done, 3)) is True
    verdict = resolve_attention(_evidence(_with_panel_rows(done, 3), pending=3))
    assert verdict.state != STATE_BUSY, verdict.detail


def test_a_session_with_no_background_work_still_rests():
    lines = [
        line
        for line in _without_shell_pill(_capture())
        if "worker" not in line and "⏺ main" not in line
    ]
    lines = [TURN_END if line == WAITING else line for line in lines]
    assert detect_resting_prompt(lines) is True


def test_the_line_above_the_box_is_found_and_only_that_line():
    lines = _capture()
    window = [line for line in lines if line.strip()][-RESTING_TAIL_LINES:]
    assert line_above_prompt_box(window, lines, RESTING_PROMPT_MARKER) == WAITING
    bare = [WAITING, "❯ "]
    assert line_above_prompt_box(bare, bare, RESTING_PROMPT_MARKER) is None
    assert line_above_prompt_box(["x"], ["x"], RESTING_PROMPT_MARKER) is None


def test_a_stale_waiting_line_in_scrollback_still_does_not_count():
    lines = [WAITING] + ["  prose %d" % n for n in range(RESTING_TAIL_LINES + 4)]
    lines += ["─" * 60, "❯ ", "─" * 62]
    assert detect_resting_prompt(lines) is True
