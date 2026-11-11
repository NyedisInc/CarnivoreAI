
from __future__ import annotations

from dataclasses import replace

from src.core.attention.background_claims import standing_background_claims
from src.core.attention.evidence import (
    REASON_RESTING_PROMPT, REASON_SUBAGENTS, STATE_BUSY, STATE_UNKNOWN,
)
from src.core.attention.resolve import resolve_attention
from src.core.background_work.measured import STATE_RUNNING, BackgroundMeasure
from tests.python.background_work.test_measured_background import _evidence

RUNNING_TWO = BackgroundMeasure(STATE_RUNNING, 2)


def test_control_open_claims_at_a_resting_prompt_read_unknown_today():
    evidence = _evidence("idle", RUNNING_TWO, resting=True)
    assert standing_background_claims(evidence) == 2
    verdict = resolve_attention(evidence)
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)


def test_claims_that_all_belong_to_finished_agents_do_not_hold_a_resting_session():
    evidence = replace(_evidence("idle", RUNNING_TWO, resting=True),
                       background_leftovers=frozenset({"b0", "b1"}))
    assert standing_background_claims(evidence) == 0
    verdict = resolve_attention(evidence)
    assert verdict.state not in (STATE_UNKNOWN, STATE_BUSY), verdict.detail
    assert verdict.reason != REASON_SUBAGENTS


def test_a_claim_of_a_live_owner_still_holds_the_session():
    evidence = replace(_evidence("idle", RUNNING_TWO, resting=False),
                       background_leftovers=frozenset({"b0"}))
    assert standing_background_claims(evidence) == 1
    verdict = resolve_attention(evidence)
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS)


def test_an_unmeasured_leftover_set_retires_nothing():
    evidence = replace(_evidence("idle", RUNNING_TWO), background_leftovers=None)
    assert standing_background_claims(evidence) == 2
