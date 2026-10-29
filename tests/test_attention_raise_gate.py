
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from src.core.attention.raise_gate import (
    LOG_MUTED,
    SUPPRESSED_NOTIFICATIONS_MUTED,
    TOAST_KINDS,
    resolve_raise,
)
from src.core.session_activity import (
    EVENT_NOTIFICATION,
    EVENT_PERMISSION_REQUEST,
    EVENT_STOP,
)


@dataclass(frozen=True)
class _Policy:

    suppresses: bool
    verdict: str = "muted"
    generation: Optional[int] = 7


def _gate(kind, *, store=False, policy=None):
    return resolve_raise(kind, policy_store_attached=store, policy=policy)




@pytest.mark.parametrize(
    "kind", [EVENT_STOP, EVENT_NOTIFICATION, EVENT_PERMISSION_REQUEST]
)
def test_a_session_with_no_policy_store_always_raises(kind):
    verdict = _gate(kind)
    assert verdict.raises_toast
    assert verdict.suppressed_by is None
    assert verdict.log_event is None


@pytest.mark.parametrize(
    "kind", [EVENT_STOP, EVENT_NOTIFICATION, EVENT_PERMISSION_REQUEST]
)
def test_a_policy_that_does_not_suppress_raises(kind):
    assert _gate(kind, store=True, policy=_Policy(suppresses=False)).raises_toast


def test_an_unreadable_policy_with_NO_store_attached_still_raises():
    assert _gate(EVENT_STOP, store=False, policy=None).raises_toast




@pytest.mark.parametrize(
    "kind", [EVENT_STOP, EVENT_NOTIFICATION, EVENT_PERMISSION_REQUEST]
)
def test_a_mute_covers_every_toast_kind_including_a_permission(kind):
    verdict = _gate(kind, store=True, policy=_Policy(suppresses=True))
    assert verdict.suppressed_by == SUPPRESSED_NOTIFICATIONS_MUTED
    assert verdict.log_event == LOG_MUTED
    assert verdict.log_fields == {
        "policy": "muted",
        "policy_generation": 7,
        "toast_kind": kind,
    }


def test_an_unreadable_policy_suppresses_once_a_store_is_attached():
    verdict = _gate(EVENT_STOP, store=True, policy=None)
    assert verdict.suppressed_by == SUPPRESSED_NOTIFICATIONS_MUTED
    assert verdict.log_fields["policy"] == "unreadable"
    assert verdict.log_fields["policy_generation"] is None




def test_the_kind_is_recorded_and_never_branched_on():
    suppressed = {
        kind: _gate(kind, store=True, policy=_Policy(suppresses=True)).suppressed_by
        for kind in TOAST_KINDS
    }
    assert set(suppressed.values()) == {SUPPRESSED_NOTIFICATIONS_MUTED}


def test_the_three_toast_kinds_are_the_vocabulary_and_not_re_spelled():
    assert TOAST_KINDS == frozenset(
        {EVENT_STOP, EVENT_NOTIFICATION, EVENT_PERMISSION_REQUEST}
    )
