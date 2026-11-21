
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.api.parked_work_listing import login_expired_for
from src.core.attention.login_notice import make_login_notice_raiser
from src.core.attention.transcript_facts import classify_transcript_records
from src.models import Toast

NOW = datetime(2026, 11, 17, 17, 0, tzinfo=timezone.utc)
LINE = "Login reached its time limit · Please run /login"


def _lockout(ts: str, **over: Any) -> Dict[str, Any]:
    record = {"type": "assistant", "isSidechain": False, "timestamp": ts, "error": "authentication_failed",
              "isApiErrorMessage": True, "message": {"model": "<synthetic>", "role": "assistant", "stop_reason": "stop_sequence",
                                                      "content": [{"type": "text", "text": LINE}]}}
    record.update(over)
    return record


def _turn_end(ts: str) -> Dict[str, Any]:
    return {"type": "system", "subtype": "turn_duration", "isSidechain": False, "timestamp": ts, "version": "2.1.325"}


def _normal(ts: str) -> List[Dict[str, Any]]:
    return [{"type": "assistant", "isSidechain": False, "timestamp": ts,
             "message": {"model": "claude-sonnet-5-5", "role": "assistant", "content": [{"type": "text", "text": "back"}]}},
            _turn_end(ts)]


def test_the_turn_that_ended_on_the_login_line_is_a_lockout():
    facts = classify_transcript_records([_lockout("2026-11-17T15:00:00.189Z"), _turn_end("2026-11-17T15:00:00.200Z")], now=NOW)
    assert facts.login_expired is not None
    assert facts.login_expired.message == LINE
    assert facts.login_expired.since == datetime(2026, 11, 17, 15, 0, 0, 189000, tzinfo=timezone.utc)


def test_repeated_lockout_records_are_one_lockout_and_a_later_normal_turn_clears_it():
    locked = [_lockout("2026-11-17T15:00:00.189Z"), _lockout("2026-11-17T15:30:00.264Z")]
    assert classify_transcript_records(locked, now=NOW).login_expired.since.minute == 30
    assert classify_transcript_records(locked + _normal("2026-11-17T16:00:00Z"), now=NOW).login_expired is None


@pytest.mark.parametrize("over", [{"isSidechain": True}, {"error": "rate_limit"}, {"isApiErrorMessage": False}])
def test_only_a_main_loop_authentication_failure_counts(over):
    assert classify_transcript_records([_lockout("2026-11-17T15:00:00Z", **over)], now=NOW).login_expired is None


def test_the_listing_wrapper_carries_the_lockout():
    facts = classify_transcript_records([_lockout("2026-11-17T15:00:00.189Z")], now=NOW)
    observation = SimpleNamespace(stale=False, evidence=SimpleNamespace(transcript=facts, codex=None))
    watcher = SimpleNamespace(observation_for=lambda _id, now=None: observation)
    info = SimpleNamespace(agent_family=None, session=SimpleNamespace(id="ses_1"))
    got = login_expired_for(watcher, info, NOW)
    assert (got.message, got.since) == (LINE, "2026-11-17T15:00:00.189000+00:00")
    assert login_expired_for(None, info, NOW) is None


class _Policy:
    def __init__(self, suppresses: bool) -> None:
        self.suppresses = suppresses


class _Manager:
    def __init__(self, muted: bool = False) -> None:
        self._notification_policy_store = object()
        self.muted = muted
        self.toasts: List[dict] = []

    def notification_policy_stamp(self, session_id: str) -> _Policy:
        return _Policy(self.muted)

    def record_toast(self, **kw: Any) -> Toast:
        self.toasts.append(kw)
        return Toast(id=f"t{len(self.toasts)}", session_id=kw["session_id"], kind=kw["kind"], title=kw["title"],
                     body=kw["body"], created_at=datetime.now(timezone.utc))


def _observation(*records: Dict[str, Any]) -> Any:
    return SimpleNamespace(evidence=SimpleNamespace(transcript=classify_transcript_records(list(records), now=NOW)))


def test_one_notification_per_lockout_not_per_poll_or_per_record_and_again_after_it_clears():
    manager, sent = _Manager(), []
    raiser = make_login_notice_raiser(manager, None, lambda sid, payload: sent.append(sid))
    target = SimpleNamespace(session_id="ses_1")
    first = _lockout("2026-11-17T15:00:00Z")
    raiser(target, _observation(first))
    raiser(target, _observation(first))
    raiser(target, _observation(first, _lockout("2026-11-17T15:30:00Z")))
    raiser(target, SimpleNamespace(evidence=SimpleNamespace(transcript=None)))
    raiser(target, _observation(first))
    assert len(manager.toasts) == 1 and sent == ["ses_1"]
    assert (manager.toasts[0]["notify_type"], manager.toasts[0]["kind"]) == ("session.attention", "Notification")
    raiser(target, _observation(first, *_normal("2026-11-17T16:00:00Z")))
    raiser(target, _observation(first, *_normal("2026-11-17T16:00:00Z"), _lockout("2026-11-17T17:00:00Z")))
    assert len(manager.toasts) == 2


def test_a_muted_session_is_not_told_and_unmuting_does_not_replay_the_old_lockout():
    manager = _Manager(muted=True)
    raiser = make_login_notice_raiser(manager, None, lambda *_a: None)
    target = SimpleNamespace(session_id="ses_1")
    observation = _observation(_lockout("2026-11-17T15:00:00Z"))
    raiser(target, observation)
    manager.muted = False
    raiser(target, observation)
    assert manager.toasts == []
