
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.session_conversation_takeover import (
    REASON_INCUMBENT_IS_THE_LIVE_ROW,
    REASON_INCUMBENT_RUNNING,
    REASON_NAME_ABSENT,
    REASON_NAME_PRESENT,
    REASON_SUCCESSOR_INSTANCE,
    REASON_UNMEASURED,
    decide_conversation_takeover,
)
from src.core.session_recreate_presence import (
    TMUX_GONE,
    TMUX_PRESENT,
    TMUX_UNKNOWN,
)

LIVE_NAME = "cloude_Shopify"
LIVE_ROW_ID = 26
RETIRED_ROW_ID = 28


def _decide(**overrides):
    args = {
        "incumbent_row_id": RETIRED_ROW_ID,
        "incumbent_lifecycle": "stopped",
        "incumbent_tmux_name": LIVE_NAME,
        "live_row_id": LIVE_ROW_ID,
        "live_tmux_name": LIVE_NAME,
        "listing_ok": True,
        "listing_complete": True,
        "names": [LIVE_NAME, "cloude_Argent"],
    }
    args.update(overrides)
    return decide_conversation_takeover(**args)


def test_a_stopped_row_sharing_the_live_name_is_measured_gone():
    decision = _decide()

    assert decision.may_take is True
    assert decision.outcome == TMUX_GONE
    assert decision.reason == REASON_SUCCESSOR_INSTANCE


def test_an_incumbent_the_app_believes_is_running_is_never_taken_from():
    decision = _decide(incumbent_lifecycle="running")

    assert decision.may_take is False
    assert decision.outcome == TMUX_UNKNOWN
    assert decision.reason == REASON_INCUMBENT_RUNNING


def test_a_listing_that_did_not_run_takes_nothing():
    decision = _decide(listing_ok=False, names=[])

    assert decision.may_take is False
    assert decision.outcome == TMUX_UNKNOWN
    assert decision.reason == REASON_UNMEASURED


def test_an_incomplete_listing_takes_nothing_from_a_name_it_did_not_carry():
    decision = _decide(
        incumbent_tmux_name="cloude_LongGone",
        listing_complete=False,
    )

    assert decision.may_take is False
    assert decision.outcome == TMUX_UNKNOWN
    assert decision.reason == REASON_UNMEASURED


def test_a_found_name_is_positive_evidence_even_on_a_partial_listing():
    decision = _decide(listing_complete=False)

    assert decision.may_take is True
    assert decision.outcome == TMUX_GONE
    assert decision.reason == REASON_SUCCESSOR_INSTANCE


def test_a_name_outside_the_namespace_takes_nothing():
    decision = _decide(
        incumbent_tmux_name="somebody_elses_tmux",
        live_tmux_name="somebody_elses_tmux",
    )

    assert decision.may_take is False
    assert decision.outcome == TMUX_UNKNOWN
    assert decision.reason == REASON_UNMEASURED


def test_a_carnivore_prefixed_incumbent_is_inside_the_namespace_too():
    decision = _decide(
        incumbent_tmux_name="carnivore_LongGone",
        names=[LIVE_NAME, "cloude_Argent"],
    )

    assert decision.may_take is True
    assert decision.outcome == TMUX_GONE
    assert decision.reason == REASON_NAME_ABSENT


def test_an_incumbent_with_its_own_pane_on_the_socket_is_present():
    decision = _decide(
        incumbent_tmux_name="cloude_Argent",
        names=[LIVE_NAME, "cloude_Argent"],
    )

    assert decision.may_take is False
    assert decision.outcome == TMUX_PRESENT
    assert decision.reason == REASON_NAME_PRESENT


def test_an_incumbent_whose_own_name_is_off_the_socket_is_gone():
    decision = _decide(
        incumbent_tmux_name="cloude_LongGone",
        names=[LIVE_NAME, "cloude_Argent"],
    )

    assert decision.may_take is True
    assert decision.outcome == TMUX_GONE
    assert decision.reason == REASON_NAME_ABSENT


def test_the_live_row_is_never_taken_from_itself():
    decision = _decide(incumbent_row_id=LIVE_ROW_ID)

    assert decision.may_take is False
    assert decision.reason == REASON_INCUMBENT_IS_THE_LIVE_ROW


def test_a_missing_row_id_on_either_side_takes_nothing():
    assert _decide(incumbent_row_id=None).may_take is False
    assert _decide(incumbent_row_id=None).reason == REASON_UNMEASURED
    assert _decide(live_row_id=None).may_take is False
    assert _decide(live_row_id=None).reason == REASON_UNMEASURED


def test_an_incumbent_with_no_tmux_name_takes_nothing():
    decision = _decide(incumbent_tmux_name=None)

    assert decision.may_take is False
    assert decision.outcome == TMUX_UNKNOWN
    assert decision.reason == REASON_UNMEASURED


def test_a_same_name_incumbent_needs_the_live_pane_on_the_socket():
    decision = _decide(names=["cloude_Argent"])

    assert decision.may_take is True
    assert decision.outcome == TMUX_GONE
    assert decision.reason == REASON_NAME_ABSENT
