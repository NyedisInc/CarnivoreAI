
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import List

from src.core.attention.evidence import EvidenceIdentity
from src.core.attention.transcript_facts import FACTS_FOUND, TranscriptFacts
from src.core.resource_push import topics
from src.core.resource_push.session_usage_watch import MAX_SESSIONS, SessionUsageWatch

T0 = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)


def _evidence(append_s: int = 0, *, end_s: int = 0, uuid: str = "u1", facts: bool = True):
    transcript = TranscriptFacts(
        verdict=FACTS_FOUND, newest_append_at=T0 + timedelta(seconds=append_s), turn_end_at=T0 + timedelta(seconds=end_s),
    ) if facts else TranscriptFacts(verdict=FACTS_FOUND)
    return SimpleNamespace(transcript=transcript, identity=EvidenceIdentity("s", "n", 1, 2, uuid))


def test_a_change_is_published_once_and_a_quiet_pass_publishes_nothing() -> None:
    sent: List[str] = []
    watch = SessionUsageWatch(publish=sent.append)
    assert watch.observe("ses_1", _evidence()) is False
    for _ in range(5):
        assert watch.observe("ses_1", _evidence()) is False
    assert sent == []
    assert watch.observe("ses_1", _evidence(append_s=3)) is True
    assert watch.observe("ses_1", _evidence(append_s=3)) is False
    assert watch.observe("ses_1", _evidence(append_s=3, end_s=3)) is True
    assert watch.observe("ses_1", _evidence(append_s=3, end_s=3, uuid="u2")) is True
    assert sent == ["ses_1"] * 3


def test_an_unread_transcript_publishes_nothing_and_keeps_the_last_signature() -> None:
    sent: List[str] = []
    watch = SessionUsageWatch(publish=sent.append)
    watch.observe("ses_1", _evidence())
    assert watch.observe("ses_1", _evidence(facts=False)) is False
    assert watch.observe("ses_1", _evidence()) is False
    assert sent == []


def test_sessions_stay_apart_and_the_memory_is_bounded() -> None:
    sent: List[str] = []
    watch = SessionUsageWatch(publish=sent.append)
    watch.observe("a", _evidence())
    watch.observe("b", _evidence())
    watch.observe("a", _evidence(append_s=1))
    assert sent == ["a"]
    for i in range(MAX_SESSIONS + 20):
        watch.observe(f"s{i}", _evidence())
    assert len(watch._last) == MAX_SESSIONS


def test_the_family_is_advertised_and_keyed_by_session_id() -> None:
    assert topics.SESSION_USAGE in topics.RESOURCE_TOPICS
    assert topics.keyed(topics.SESSION_USAGE, "ses_1") == "session_usage:ses_1"
    assert topics.family_of("session_usage:ses_1") == topics.SESSION_USAGE


def test_the_attention_side_effects_feed_the_watch_on_every_observation() -> None:
    from src.core.attention.side_effects import AttentionSideEffects
    from tests.test_attention_side_effects import RecordingManager, SESSION_ID, TARGET, observation, registry_ok

    effects = AttentionSideEffects(RecordingManager(), broadcast_toast_ack=lambda *a: None, broadcast_rename=lambda *a: None)
    seen: List[str] = []
    effects._usage_watch = SessionUsageWatch(publish=seen.append)
    def facts(extra: int) -> TranscriptFacts:
        return TranscriptFacts(verdict=FACTS_FOUND, newest_append_at=T0 + timedelta(seconds=extra), turn_end_at=T0)

    effects.on_observation(TARGET, observation(registry=registry_ok(), transcript=facts(0)))
    effects.on_observation(TARGET, observation(registry=registry_ok(), transcript=facts(9)))
    assert seen == [SESSION_ID]
