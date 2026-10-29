
from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone

import pytest

from src.core.attention import side_effects as side_effects_module
from src.core.attention.evidence import (
    AttentionVerdict,
    Evidence,
    FAMILY_CLAUDE,
    REASON_STREAMING,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    TIER_REGISTRY,
)
from src.core.attention.ledger import AttentionLedger
from src.core.attention.registry_record import REG_STALE, parse_registry_record
from src.core.attention.registry_index import registry_for_session
from src.core.attention.side_effects import AttentionSideEffects
from src.core.attention.transcript_facts import FACTS_FOUND, TranscriptFacts
from src.core.attention.watcher import Observation, WatchTarget
from src.core.db_models import SESSION_CLAUDE_UUID_SOURCE_REGISTRY
from src.core.session_lineage import (
    LINEAGE_BOUND,
    LINEAGE_CONTINUED,
    LINEAGE_UNRESOLVED,
    LineageResult,
)
from src.core.session_startup_gate_ledger import StartupGateLedger
from src.core.session_status import LIVENESS_LIVE

NOW = datetime(2026, 9, 13, 18, 0, 0, tzinfo=timezone.utc)
TMUX_NAME = "cloude_sideeffects"
EPOCH = 1789095742
SESSION_ID = "ses_side"
TARGET = WatchTarget(session_id=SESSION_ID, key="%s@%d" % (TMUX_NAME, EPOCH))

CONVERSATION_UUID = "11111111-2222-3333-4444-555555555555"

TRUST_DIALOG_TAIL = "  Yes, I trust this folder"




class RecordingManager:

    def __init__(self) -> None:
        self._registry = types.SimpleNamespace(backends={})
        self.hook_tokens = types.SimpleNamespace(name_for=lambda sid: TMUX_NAME)
        self._instance_epochs = {SESSION_ID: EPOCH}
        self._startup_gate_ledger = StartupGateLedger()
        self._unread_store = types.SimpleNamespace(set_flag=self._set_flag)
        self.unread_writes: list = []
        self.state_writes: list = []
        self.work_stamps: list = []
        self.work_stamp_kwargs: list = []
        self.acks: list = []
        self.ack_returns: list = []
        self.lifecycle_events: list = []
        self.lifecycle_outcomes: list = []

    def _set_flag(self, tmux_name, field_name, value, epoch=None):
        self.unread_writes.append((tmux_name, field_name, value, epoch))

    def _writable_datastore_connection(self):
        return None

    def tmux_socket_name(self):
        return "cloudetest"

    def _unread_epoch(self, tmux_name):
        return EPOCH

    def _persist_settled_activity_state(self, tmux_name, state, epoch):
        self.state_writes.append((tmux_name, state, epoch))

    def _persist_work_stamp(self, session_id, tmux_name, kind, **stamp):
        self.work_stamps.append((session_id, tmux_name, kind))
        self.work_stamp_kwargs.append(stamp)
        return True

    def auto_ack_toasts(self, session_id, event_kind, cutoff=None):
        self.acks.append((session_id, event_kind, cutoff))
        return list(self.ack_returns)

    def record_claude_lifecycle_event(
        self, session_id, event_kind, payload, *, uuid_source="hook",
        tmux_name=None,
    ):
        self.lifecycle_events.append(
            (session_id, event_kind, payload, uuid_source, tmux_name)
        )
        outcome = (
            self.lifecycle_outcomes.pop(0)
            if self.lifecycle_outcomes
            else LINEAGE_BOUND
        )
        return LineageResult(outcome=outcome, row_id=1)


@pytest.fixture()
def wired(monkeypatch):
    calls = {"infer": [], "title": [], "ack_frames": [], "rename_frames": []}

    def fake_infer(manager, session_id, tmux_name):
        calls["infer"].append((session_id, tmux_name))
        return None

    def fake_title(manager, session_id):
        calls["title"].append(session_id)
        return types.SimpleNamespace(broadcast_title=None)

    monkeypatch.setattr(
        side_effects_module.session_agent_infer_apply,
        "apply_agent_inference",
        fake_infer,
    )
    monkeypatch.setattr(
        side_effects_module.claude_title_sync_apply, "sync_claude_title", fake_title
    )
    manager = RecordingManager()
    effects = AttentionSideEffects(
        manager,
        broadcast_toast_ack=lambda sid, tid: calls["ack_frames"].append((sid, tid)),
        broadcast_rename=lambda sid, name: calls["rename_frames"].append((sid, name)),
    )
    return manager, effects, calls




def registry_ok(
    status: str = "idle",
    session_uuid: str = CONVERSATION_UUID,
    started_at_epoch: int = EPOCH,
):
    return parse_registry_record(
        {
            "pid": 4242,
            "status": status,
            "sessionId": session_uuid,
            "cwd": "/tmp",
            "tmux": "%s:@0.%%0" % TMUX_NAME,
            "version": "2.1.266",
            "startedAt": started_at_epoch * 1000,
        },
        path_pid=4242,
    )


def registry_unreadable():
    return parse_registry_record({}, path_pid=None)


def registry_conversation_mismatch():
    stale = registry_for_session(
        tmux_name=TMUX_NAME,
        index={TMUX_NAME: registry_ok(status="busy")},
        claude_session_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    assert stale.verdict == REG_STALE
    return stale


def facts(**fields) -> TranscriptFacts:
    fields.setdefault("verdict", FACTS_FOUND)
    return TranscriptFacts(**fields)


def evidence(*, registry=None, transcript=None, now=NOW) -> Evidence:
    return Evidence(
        tmux_liveness=LIVENESS_LIVE,
        agent_family=FAMILY_CLAUDE,
        registry=registry if registry is not None else registry_ok(),
        transcript=transcript if transcript is not None else facts(),
        pane=None,
        now=now,
    )


def verdict(state: str = STATE_DONE_IDLE, reason: str = REASON_TURN_ENDED):
    return AttentionVerdict(state=state, reason=reason, tier=TIER_REGISTRY)


def observation(
    *, registry=None, transcript=None, prompt_at=None, appended=False, state=None
) -> Observation:
    return Observation(
        verdict=verdict() if state is None else verdict(state=state, reason=REASON_STREAMING),
        evidence=evidence(registry=registry, transcript=transcript),
        new_user_prompt_at=prompt_at,
        transcript_appended=appended,
    )




def test_a_registry_record_opens_the_startup_gate(wired):
    from src.core.session_startup_gate import GATE_READY, resolve_startup_gate

    manager, effects, _calls = wired
    effects.on_observation(TARGET, observation(registry=registry_ok()))

    first = manager._startup_gate_ledger.first_hook_at(TMUX_NAME)
    assert first is not None
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=first,
            instance_age_seconds=600.0,
            tail=TRUST_DIALOG_TAIL,
        )
        == GATE_READY
    )


def test_no_registry_record_leaves_the_startup_gate_shut(wired):
    from src.core.session_startup_gate import GATE_AWAITING, resolve_startup_gate

    manager, effects, _calls = wired
    effects.on_observation(TARGET, observation(registry=registry_unreadable()))
    first = manager._startup_gate_ledger.first_hook_at(TMUX_NAME)
    assert first is None
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=first,
            instance_age_seconds=600.0,
            tail=TRUST_DIALOG_TAIL,
        )
        == GATE_AWAITING
    )


def test_a_record_naming_another_conversation_still_proves_a_start(wired):
    from src.core.session_startup_gate import GATE_READY, resolve_startup_gate

    manager, effects, _calls = wired
    mismatch = registry_conversation_mismatch()
    assert mismatch.known is False

    effects.on_observation(TARGET, observation(registry=mismatch))

    first = manager._startup_gate_ledger.first_hook_at(TMUX_NAME)
    assert first is not None
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=first,
            instance_age_seconds=600.0,
            tail=TRUST_DIALOG_TAIL,
        )
        == GATE_READY
    )


def test_a_record_from_a_previous_instance_does_not_prove_a_start(wired):
    from src.core.session_startup_gate import GATE_AWAITING, resolve_startup_gate

    manager, effects, _calls = wired
    previous = registry_for_session(
        tmux_name=TMUX_NAME,
        index={TMUX_NAME: registry_ok()},
        session_started_epoch=EPOCH + 86_400,
    )
    assert previous.verdict == REG_STALE

    effects.on_observation(TARGET, observation(registry=previous))

    first = manager._startup_gate_ledger.first_hook_at(TMUX_NAME)
    assert first is None
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=first,
            instance_age_seconds=600.0,
            tail=TRUST_DIALOG_TAIL,
        )
        == GATE_AWAITING
    )


def test_the_startup_stamp_is_first_write_wins(wired):
    manager, effects, _calls = wired
    effects.on_observation(TARGET, observation(registry=registry_ok()))
    first = manager._startup_gate_ledger.first_hook_at(TMUX_NAME)
    effects.on_observation(TARGET, observation(registry=registry_ok()))
    assert manager._startup_gate_ledger.first_hook_at(TMUX_NAME) == first




def test_a_registry_record_triggers_the_agent_inference(wired):
    _manager, effects, calls = wired
    effects.on_observation(TARGET, observation(registry=registry_ok()))
    assert calls["infer"] == [(SESSION_ID, TMUX_NAME)]


def test_a_growing_transcript_triggers_the_agent_inference(wired):
    _manager, effects, calls = wired
    effects.on_observation(
        TARGET, observation(registry=registry_unreadable(), appended=True)
    )
    assert calls["infer"] == [(SESSION_ID, TMUX_NAME)]


def test_no_sign_of_life_does_not_trigger_the_agent_inference(wired):
    _manager, effects, calls = wired
    effects.on_observation(
        TARGET, observation(registry=registry_unreadable(), appended=False)
    )
    assert calls["infer"] == []




def test_the_done_edge_sets_the_auto_unread_flag(wired):
    manager, effects, _calls = wired
    effects.set_unread(TARGET)
    assert manager.unread_writes == [(TMUX_NAME, "auto", True, EPOCH)]


def test_a_session_with_no_tmux_name_sets_no_flag(wired):
    manager, effects, _calls = wired
    manager.hook_tokens.name_for = lambda sid: None
    effects.set_unread(TARGET)
    assert manager.unread_writes == []




def test_every_reading_makes_the_resolved_state_durable(wired):
    manager, effects, _calls = wired
    effects.on_observation(TARGET, observation())
    assert manager.state_writes == [(TMUX_NAME, "idle", EPOCH)]


def test_a_busy_reading_persists_working_not_idle(wired):
    manager, effects, _calls = wired
    effects.on_observation(TARGET, observation(state=STATE_BUSY))
    assert manager.state_writes == [(TMUX_NAME, "working", EPOCH)]


def test_no_tmux_name_persists_nothing(wired):
    manager, effects, _calls = wired
    manager.hook_tokens.name_for = lambda sid: None
    effects.on_observation(TARGET, observation())
    assert manager.state_writes == []




def test_a_new_user_prompt_stamps_the_work_time(wired):
    manager, effects, _calls = wired
    effects.on_observation(TARGET, observation(prompt_at=NOW))
    assert manager.work_stamps == [(SESSION_ID, TMUX_NAME, None)]


def test_the_busy_edge_stamps_the_work_time(wired):
    from src.core.attention.ledger import Transition

    manager, effects, _calls = wired
    effects.on_busy_edge(
        TARGET,
        Transition(
            key=TARGET.key,
            state=STATE_BUSY,
            reason=REASON_STREAMING,
            verdict=verdict(state=STATE_BUSY, reason=REASON_STREAMING),
            previous_state=STATE_DONE_IDLE,
            at=NOW,
        ),
    )
    assert manager.work_stamps == [(SESSION_ID, TMUX_NAME, None)]


def test_a_quiet_reading_stamps_nothing(wired):
    manager, effects, _calls = wired
    effects.on_observation(TARGET, observation())
    assert manager.work_stamps == []


def test_a_none_kind_reaches_the_real_stamp():
    from src.core.session_manager import SessionManager

    calls: list = []
    probe = types.SimpleNamespace(
        _last_work_stamp_at={},
        _instance_epochs={},
        _work_stamp_epoch=lambda sid, name: calls.append((sid, name)) or None,
    )
    SessionManager._persist_work_stamp(probe, "ses_a", "cloude_x", None)
    assert calls == [("ses_a", "cloude_x")]
    SessionManager._persist_work_stamp(probe, "ses_b", "cloude_x", "SessionStart")
    assert len(calls) == 1




def test_a_new_user_prompt_clears_the_pending_toasts(wired):
    manager, effects, calls = wired
    manager.ack_returns = ["toast_1", "toast_2"]
    effects.on_observation(TARGET, observation(prompt_at=NOW))

    assert len(manager.acks) == 1
    session_id, kind, cutoff = manager.acks[0]
    assert (session_id, kind) == (SESSION_ID, "UserPromptSubmit")
    assert calls["ack_frames"] == [
        (SESSION_ID, "toast_1"),
        (SESSION_ID, "toast_2"),
    ]


def test_a_task_notification_clears_nothing(wired):
    from src.core.attention.transcript_facts import classify_transcript_records

    manager, effects, _calls = wired
    stamp = NOW.isoformat().replace("+00:00", "Z")
    notice = {
        "type": "user",
        "timestamp": stamp,
        "origin": {"kind": "task-notification"},
        "promptSource": "system",
        "message": {
            "role": "user",
            "content": "<task-notification><status>completed</status>",
        },
    }
    read = classify_transcript_records([notice], now=NOW)
    assert read.newest_user_prompt_at is None, "the reader counted a notice"

    ledger = AttentionLedger()
    ledger.note_transcript(
        TARGET.key, user_prompt_at=None, append_at=NOW - timedelta(seconds=60)
    )
    new_prompt, _appended = ledger.note_transcript(
        TARGET.key,
        user_prompt_at=read.newest_user_prompt_at,
        append_at=read.newest_append_at,
    )
    effects.on_observation(
        TARGET, observation(prompt_at=new_prompt, appended=_appended)
    )
    assert manager.acks == []
    assert manager.work_stamps == []


def test_a_real_user_prompt_survives_the_same_reader(wired):
    from src.core.attention.transcript_facts import classify_transcript_records

    manager, effects, _calls = wired
    stamp = NOW.isoformat().replace("+00:00", "Z")
    typed = {
        "type": "user",
        "timestamp": stamp,
        "message": {"role": "user", "content": "run the tests"},
    }
    read = classify_transcript_records([typed], now=NOW)
    assert read.newest_user_prompt_at is not None

    ledger = AttentionLedger()
    ledger.note_transcript(
        TARGET.key, user_prompt_at=None, append_at=NOW - timedelta(seconds=60)
    )
    new_prompt, appended = ledger.note_transcript(
        TARGET.key,
        user_prompt_at=read.newest_user_prompt_at,
        append_at=read.newest_append_at,
    )
    assert new_prompt is not None
    effects.on_observation(TARGET, observation(prompt_at=new_prompt, appended=appended))
    assert [call[1] for call in manager.acks] == ["UserPromptSubmit"]
    assert manager.work_stamps == [(SESSION_ID, TMUX_NAME, None)]


def test_the_ack_cutoff_is_aware_utc(wired):
    manager, effects, _calls = wired
    effects.on_observation(TARGET, observation(prompt_at=NOW))
    cutoff = manager.acks[0][2]
    assert cutoff is not None and cutoff.utcoffset() == timedelta(0)
    assert cutoff == NOW


def test_the_busy_edge_answers_a_permission_and_nothing_else(wired):
    from src.core.attention.ledger import Transition
    from src.core.toast_auto_ack import kinds_answered_by

    manager, effects, _calls = wired
    effects.on_busy_edge(
        TARGET,
        Transition(
            key=TARGET.key,
            state=STATE_BUSY,
            reason=REASON_STREAMING,
            verdict=verdict(state=STATE_BUSY, reason=REASON_STREAMING),
            previous_state=STATE_DONE_IDLE,
            at=NOW,
        ),
    )
    assert [call[1] for call in manager.acks] == ["PreToolUse"]
    assert kinds_answered_by("PreToolUse") == frozenset({"PermissionRequest"})




def test_a_growing_transcript_pulls_the_claude_title(wired):
    _manager, effects, calls = wired
    effects.on_observation(TARGET, observation(appended=True))
    assert calls["title"] == [SESSION_ID]


def test_a_quiet_transcript_pulls_nothing(wired):
    _manager, effects, calls = wired
    effects.on_observation(TARGET, observation(appended=False))
    assert calls["title"] == []


def test_a_changed_title_reaches_the_wire(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        side_effects_module.claude_title_sync_apply,
        "sync_claude_title",
        lambda manager, sid: types.SimpleNamespace(broadcast_title="renamed"),
    )
    monkeypatch.setattr(
        side_effects_module.session_agent_infer_apply,
        "apply_agent_inference",
        lambda manager, sid, name: None,
    )
    effects = AttentionSideEffects(
        RecordingManager(),
        broadcast_rename=lambda sid, name: calls.append((sid, name)),
    )
    effects.on_observation(TARGET, observation(appended=True))
    assert calls == [(SESSION_ID, "renamed")]




def test_one_failing_job_does_not_stop_the_others(wired):
    manager, effects, calls = wired

    def boom(*args, **kwargs):
        raise RuntimeError("the process table went away")

    monkey = side_effects_module.session_agent_infer_apply
    original = monkey.apply_agent_inference
    monkey.apply_agent_inference = boom
    try:
        effects.on_observation(TARGET, observation(prompt_at=NOW, appended=True))
    finally:
        monkey.apply_agent_inference = original

    assert manager._startup_gate_ledger.first_hook_at(TMUX_NAME) is not None
    assert manager.state_writes and manager.work_stamps and manager.acks
    assert calls["title"] == [SESSION_ID]




def test_the_first_reading_is_not_a_new_user_prompt():
    ledger = AttentionLedger()
    new_prompt, appended = ledger.note_transcript(
        "k", user_prompt_at=NOW - timedelta(hours=9), append_at=NOW
    )
    assert new_prompt is None
    assert appended is True, "an append on first sight is a cheap, idempotent pull"


def test_a_later_prompt_is_news_and_the_same_one_is_not():
    ledger = AttentionLedger()
    ledger.note_transcript("k", user_prompt_at=NOW, append_at=NOW)
    again, _ = ledger.note_transcript("k", user_prompt_at=NOW, append_at=NOW)
    assert again is None
    later = NOW + timedelta(seconds=5)
    fresh, appended = ledger.note_transcript("k", user_prompt_at=later, append_at=later)
    assert fresh == later
    assert appended is True


def test_an_unchanged_transcript_is_not_an_append():
    ledger = AttentionLedger()
    ledger.note_transcript("k", user_prompt_at=None, append_at=NOW)
    _prompt, appended = ledger.note_transcript("k", user_prompt_at=None, append_at=NOW)
    assert appended is False


def test_forgetting_an_instance_drops_its_baselines():
    ledger = AttentionLedger()
    ledger.note_transcript("k", user_prompt_at=NOW, append_at=NOW)
    ledger.forget("k")
    new_prompt, appended = ledger.note_transcript(
        "k", user_prompt_at=NOW, append_at=NOW
    )
    assert new_prompt is None and appended is True




@pytest.mark.asyncio
async def test_the_watcher_runs_the_observation_jobs_every_tick(wired):
    import os

    from src.core.attention.watcher import AttentionWatcher

    manager, effects, calls = wired
    reading = evidence(registry=registry_ok(), transcript=facts(newest_append_at=NOW))
    watcher = AttentionWatcher(
        list_targets=lambda: [TARGET],
        read_evidence=lambda target, now: reading,
        raise_toast=lambda target, kind, transition: None,
        set_unread=effects.set_unread,
        on_busy_edge=effects.on_busy_edge,
        on_observation=effects.on_observation,
        ledger=AttentionLedger(),
        now=lambda: NOW,
        tick_seconds=0.0,
        registry_directory=os.path.join(os.sep, "no-such-registry-dir"),
    )
    await watcher.tick_once()

    assert manager._startup_gate_ledger.first_hook_at(TMUX_NAME) is not None
    assert calls["infer"] == [(SESSION_ID, TMUX_NAME)]
    assert calls["title"] == [SESSION_ID]
    assert manager.state_writes


@pytest.mark.asyncio
async def test_a_watcher_with_no_observation_wiring_still_ticks():
    import os

    from src.core.attention.watcher import AttentionWatcher

    reading = evidence()
    watcher = AttentionWatcher(
        list_targets=lambda: [TARGET],
        read_evidence=lambda target, now: reading,
        raise_toast=lambda target, kind, transition: None,
        set_unread=lambda target: None,
        on_busy_edge=lambda target, transition: None,
        ledger=AttentionLedger(),
        now=lambda: NOW,
        tick_seconds=0.0,
        registry_directory=os.path.join(os.sep, "no-such-registry-dir"),
    )
    assert await watcher.tick_once() == 0




def test_a_live_registry_record_binds_its_conversation_to_the_row():
    manager, effects, _calls = _fresh()
    effects.on_observation(TARGET, observation(registry=registry_ok()))

    assert len(manager.lifecycle_events) == 1
    (
        session_id,
        event_kind,
        payload,
        uuid_source,
        pane,
    ) = manager.lifecycle_events[0]
    assert session_id == SESSION_ID
    assert event_kind == "SessionStart"
    assert payload["session_id"] == CONVERSATION_UUID
    assert uuid_source == SESSION_CLAUDE_UUID_SOURCE_REGISTRY
    assert pane == TMUX_NAME


def test_no_registry_record_binds_nothing():
    manager, effects, _calls = _fresh()
    effects.on_observation(TARGET, observation(registry=registry_unreadable()))
    assert manager.lifecycle_events == []


def test_a_registry_record_with_no_conversation_binds_nothing():
    manager, effects, _calls = _fresh()
    effects.on_observation(
        TARGET, observation(registry=registry_ok(session_uuid=None))
    )
    assert manager.lifecycle_events == []


def test_the_binding_is_not_re_issued_on_every_tick():
    manager, effects, _calls = _fresh()
    for _ in range(5):
        effects.on_observation(TARGET, observation(registry=registry_ok()))
    assert len(manager.lifecycle_events) == 1


def test_a_binding_the_writer_settled_as_already_known_also_stops():
    manager, effects, _calls = _fresh()
    manager.lifecycle_outcomes = [LINEAGE_CONTINUED]
    effects.on_observation(TARGET, observation(registry=registry_ok()))
    effects.on_observation(TARGET, observation(registry=registry_ok()))
    assert len(manager.lifecycle_events) == 1


def test_a_binding_that_could_not_be_evaluated_is_retried():
    manager, effects, _calls = _fresh()
    manager.lifecycle_outcomes = [LINEAGE_UNRESOLVED]
    effects.on_observation(TARGET, observation(registry=registry_ok()))
    effects.on_observation(TARGET, observation(registry=registry_ok()))
    assert len(manager.lifecycle_events) == 2


def test_a_new_conversation_in_the_same_pane_binds_again():
    manager, effects, _calls = _fresh()
    effects.on_observation(TARGET, observation(registry=registry_ok()))
    other = "99999999-8888-7777-6666-555555555555"
    effects.on_observation(
        TARGET, observation(registry=registry_ok(session_uuid=other))
    )
    assert [event[2]["session_id"] for event in manager.lifecycle_events] == [
        CONVERSATION_UUID,
        other,
    ]


def test_a_record_naming_another_conversation_never_reaches_the_writer():
    manager, effects, _calls = _fresh()
    stale = registry_for_session(
        tmux_name=TMUX_NAME,
        index={TMUX_NAME: registry_ok()},
        claude_session_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    assert stale.verdict == REG_STALE

    effects.on_observation(TARGET, observation(registry=stale))
    assert manager.lifecycle_events == []


def test_a_registry_source_can_never_mint_a_lineage_row():
    from src.core.session_lineage_divergence import (
        DIVERGENCE_SIBLING_PROCESS,
        SESSION_START_SOURCE_REGISTRY,
        classify_uuid_divergence,
        mints_a_row,
    )

    verdict_for_registry = classify_uuid_divergence(SESSION_START_SOURCE_REGISTRY)
    assert verdict_for_registry == DIVERGENCE_SIBLING_PROCESS
    assert mints_a_row(verdict_for_registry) is False


def _fresh():
    calls = {"infer": [], "title": []}
    manager = RecordingManager()
    effects = AttentionSideEffects(manager)
    effects._infer_agent = lambda *a: calls["infer"].append(a)
    effects._sync_title = lambda *a: calls["title"].append(a)
    return manager, effects, calls


def test_a_session_with_no_resolvable_pane_binds_nothing():
    manager, effects, _calls = _fresh()
    effects._bind_conversation(SESSION_ID, None, registry_ok())
    assert manager.lifecycle_events == []
