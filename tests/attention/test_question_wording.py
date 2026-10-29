
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.core.approvals.extract import extract_dialog
from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    Evidence,
)
from src.core.attention.pane_markers import classify_pane_tail
from src.core.attention.registry_index import registry_for_session
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import FACTS_NO_RECORD, TranscriptFacts
from src.core.session_status import LIVENESS_LIVE
from src.core.hook_event_presentation import (
    hook_event_presentation,
    question_toast_title,
)

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "approvals"
MULTI_PART_2 = (FIXTURES / "claude_multi_question.txt").read_text().replace("☐ Colour", "☒ Colour")


def _verdict(text: str):
    pane = classify_pane_tail(text.splitlines())
    evidence = Evidence(
        tmux_liveness=LIVENESS_LIVE,
        agent_family=FAMILY_CLAUDE,
        registry=registry_for_session(tmux_name="cloude_x-1", index={}),
        transcript=TranscriptFacts(verdict=FACTS_NO_RECORD),
        pane=pane,
        now=NOW,
        dialog=extract_dialog(text, FAMILY_CLAUDE) if pane.shows_dialog else None,
    )
    return resolve_attention(evidence)


def test_question_says_question_with_its_part_and_permission_keeps_its_wording() -> None:
    two_of_two = _verdict(MULTI_PART_2)
    assert (two_of_two.state, two_of_two.reason) == ("needs_user", "question")
    assert two_of_two.activity_hint == "question:2/2"
    assert question_toast_title(two_of_two.activity_hint) == "question 2 of 2 waiting"

    part_one = _verdict((FIXTURES / "claude_multi_question.txt").read_text())
    assert part_one.activity_hint == "question:1/2"

    single = _verdict((FIXTURES / "claude_single.txt").read_text())
    assert single.reason == "question" and single.activity_hint == "question"
    assert question_toast_title(single.activity_hint) == "question waiting"

    permission = _verdict((FIXTURES / "claude_permission.txt").read_text())
    assert permission.reason == "permission" and permission.activity_hint is None
    assert hook_event_presentation("PermissionRequest", {})[0] == "needs your permission"
