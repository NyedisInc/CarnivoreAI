
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Dict, List, Optional

import pytest
from fastapi import HTTPException

from src.config.provider_account_switch import ProviderAccountSwitchConfig
from src.config.provider_accounts import ProviderAccount
from src.core.account_switch import auto_restart, limit_detect
from src.core.account_switch.rotate_state import RotationState
from src.core.attention.usage_limit import LimitStop
from src.core.account_switch.pane_account import UNREADABLE, PaneProfile
from src.models.provider_ledger import (
    AccountUsage,
    LedgerSnapshot,
    LedgerTotal,
    LoopStatus,
    UsageWindow,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

REAL = [
    "You've hit your session limit · resets 4pm (America/New_York)",
    "You've hit your session limit · resets 10:30pm (America/New_York) · progress saved",
    "You've hit your weekly limit · resets 1am (America/New_York)",
    "Claude AI usage limit reached|1790000000",
]


def limit_record(text: str = REAL[0]) -> dict:
    return {
        "type": "assistant",
        "isApiErrorMessage": True,
        "error": "rate_limit",
        "quotaLimits": {"status": "rejected", "rateLimitType": "seven_day", "resetsAt": 1790000000},
        "message": {"model": "<synthetic>", "content": [{"type": "text", "text": text}]},
    }


def user_record(text: str = "go on") -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}




def test_every_real_shape_is_a_limit_sentence():
    assert all(limit_detect.is_limit_text(text) for text in REAL)
    assert not limit_detect.is_limit_text("the rate of change hit a limit in the test")


def test_the_transcript_is_blocked_only_when_the_last_turn_is_the_limit_stop():
    assert limit_detect.transcript_blocked([user_record(), limit_record()])
    assert limit_detect.transcript_blocked([user_record(), limit_record(), {"type": "system"}])
    assert not limit_detect.transcript_blocked([limit_record(), user_record("continue")])
    assert not limit_detect.transcript_blocked([])


def test_a_subagent_record_or_a_transient_429_is_not_the_last_turn():
    sidechain = dict(limit_record(), isSidechain=True)
    assert not limit_detect.transcript_blocked([user_record(), sidechain])
    transient = {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit", "apiErrorIsTransient": True,
                 "message": {"content": [{"type": "text",
                                          "text": "API Error: Server is temporarily limiting requests (not your usage limit)"}]}}
    assert not limit_detect.is_limit_record(transient)
    assert not limit_detect.is_limit_record(dict(transient, error="server_error"))


def test_the_quota_object_is_the_proof_whatever_the_wording():
    odd = limit_record("You've reached your Fable limit")
    assert limit_detect.is_limit_record(odd)
    assert not limit_detect.is_limit_record(dict(odd, quotaLimits={"status": "allowed_warning"}))
    stop = limit_detect.last_limit_stop([user_record(), dict(odd, uuid="u1", timestamp="2026-09-25T10:00:00Z")])
    assert (stop.uuid, stop.rate_limit_type, stop.kind) == ("u1", "seven_day", "weekly")
    assert stop.resets_at == datetime.fromtimestamp(1790000000, tz=timezone.utc)


def test_a_record_with_no_quota_object_falls_back_to_the_older_shapes():
    old = {k: v for k, v in limit_record().items() if k != "quotaLimits"}
    assert limit_detect.is_limit_record(old)
    assert limit_detect.is_limit_record({"type": "assistant", "isApiErrorMessage": True, "apiError": "usage_limit_reached"})
    assert not limit_detect.is_limit_record(dict(old, error="authentication_failed", message={"content": "x"}))


def test_a_quoted_sentence_is_not_a_limit_stop():
    quoted = {"type": "assistant", "message": {"content": [{"type": "text", "text": REAL[0]}]}}
    assert not limit_detect.transcript_blocked([user_record(REAL[0])])
    assert not limit_detect.transcript_blocked([user_record(), quoted])


def test_the_pane_is_blocked_only_by_its_last_lines():
    tail = "\n".join(["work"] * 3 + [REAL[0], "> "])
    assert limit_detect.pane_blocked(tail)
    scrolled = "\n".join([REAL[0]] + ["later output"] * 20)
    assert not limit_detect.pane_blocked(scrolled)
    assert not limit_detect.pane_blocked("")




def row(account_id: str, pct: float, state: str = "ok") -> AccountUsage:
    return AccountUsage(
        id=account_id, name=account_id, provider="claude", credential_state=state,
        windows=[UsageWindow(kind="five_hour", label="5h", used_pct=pct,
                             window_seconds=18000, resets_at=NOW + timedelta(hours=1))],
    )


ACCOUNTS = [
    ProviderAccount(id="old", name="old", provider="claude", claude_config_dir="/p/old"),
    ProviderAccount(id="new", name="new", provider="claude", claude_config_dir="/p/new"),
]

STOP = LimitStop(uuid="rec-1", timestamp=NOW - timedelta(hours=1), resets_at=NOW + timedelta(hours=2),
                 rate_limit_type="seven_day")


FRESH_STOP = LimitStop(uuid="rec-1", timestamp=NOW - timedelta(seconds=30), resets_at=NOW + timedelta(hours=2),
                       rate_limit_type="seven_day")


def info(name: str = "cloude_a", status: str = "unknown", family: str = "claude", hint: Optional[str] = None):
    return SimpleNamespace(
        tmux_session=name, agent_family=family, activity_status=status, activity_hint=hint, label=None,
        session=SimpleNamespace(id=f"id_{name}", working_dir="/w", tmux_created_epoch=7),
    )


class Manager:

    def __init__(self, rows, fresh_status: Optional[str] = None, result=None):
        self.rows = rows
        self.result = result or {"ok": True, "kind": "agent", "conversation": "resumed"}
        self.fresh_status = fresh_status
        self.respawned: List[tuple] = []

    async def list_session_infos(self):
        return list(self.rows)

    async def get_session_info(self, session_id):
        for r in self.rows:
            if r.session.id == session_id:
                return info(r.tmux_session, self.fresh_status or r.activity_status, r.agent_family, r.activity_hint)
        return None

    async def respawn_session(self, name, **kwargs):
        self.respawned.append((name, kwargs))
        return dict(self.result)

    def _tmux_socket_name(self):
        return "unused"


class Evidence:

    def __init__(self, blocked=("cloude_a",), resumable=True, quiet=600.0, stops=None, started=None, stop=STOP):
        self.names = set(blocked)
        self._resumable = resumable
        self._quiet = quiet
        self._stops = list(stops) if stops else None
        self._started = started
        self._stop = stop

    async def limit_stop(self, i):
        if i.tmux_session not in self.names:
            return None
        return self._stops.pop(0) if self._stops else self._stop

    async def body_started_at(self, i):
        return self._started

    async def resumable(self, name):
        return self._resumable

    async def quiet_seconds(self, name):
        return self._quiet


class Rotation:

    def __init__(self, pinned=None, ready=True, refuse_paste=False, launchable=True):
        self.pinned = pinned
        self.ready = ready
        self.refuse_paste = refuse_paste
        self._launchable = launchable
        self.moved: List[tuple] = []
        self.pasted: List[tuple] = []
        self.notices: List[tuple] = []
        self.moved_flags: List[bool] = []
        self.uuid: Optional[str] = "uuid-1"
        self.pin_reads: List[object] = []

    async def session_uuid(self, info):
        return self.uuid

    async def pin_for(self, session_uuid):
        if self.pin_reads:
            value = self.pin_reads.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        return self.pinned

    async def launchable(self, account):
        return self._launchable

    async def move_pointer(self, accounts, switch, from_id, to_id):
        self.moved.append((from_id, to_id))
        return True

    async def wait_ready(self, session_id):
        return self.ready

    async def paste_continue(self, info, session_uuid):
        if self.refuse_paste:
            raise HTTPException(status_code=409, detail={"code": "pane_dialog_open"})
        self.pasted.append((info.session.id, session_uuid))

    def notify(self, outcome, *, session, from_account_id, to_account_id, limit_kind, moved=False, from_name="", to_name=""):
        self.notices.append((outcome, session, from_account_id, to_account_id, limit_kind))
        self.moved_flags.append(moved)


def profiles(mapping: Dict[str, Optional[str]], after: str = "/p/new"):
    seen: Dict[str, int] = {}

    async def read(socket, name, variable):
        seen[name] = seen.get(name, 0) + 1
        value = mapping.get(name, "/p/old") if seen[name] == 1 else after
        return UNREADABLE if value is None else PaneProfile(True, value)

    return read


@pytest.fixture
def state(tmp_path):
    st = RotationState(tmp_path / "limit_rotation.json", clock=lambda: NOW.timestamp())
    st.take_baseline({})
    return st


@pytest.fixture(autouse=True)
def clear_skip_log():
    auto_restart._SKIP_LOGGED.clear()
    yield
    auto_restart._SKIP_LOGGED.clear()


@pytest.fixture(autouse=True)
def blank_pane(monkeypatch):
    real = auto_restart._tmux_output

    async def no_capture(socket, *args):
        return None if args and args[0] == "capture-pane" else await real(socket, *args)

    monkeypatch.setattr(auto_restart, "_tmux_output", no_capture)


def run(manager, state, *, rotation=None, snap=None, switch=None, evidence=None, read=None, clock=100.0,
        fresh_switch=None, accounts=None):
    snap = snap or LedgerSnapshot(
        accounts=[row("old", 100), row("new", 5)], total=LedgerTotal(accounts=2), loop=LoopStatus(alive=True),
    )
    switch = switch or ProviderAccountSwitchConfig(auto_switch=True, active_claude="old")
    return asyncio.run(auto_restart.restart_blocked_sessions(
        manager, snap, accounts or ACCOUNTS, switch, now=NOW, monotonic=lambda: clock,
        evidence=evidence or Evidence(), read_profile=read or profiles({}),
        current_switch=lambda: fresh_switch or switch, rotation=rotation or Rotation(), state=state,
    ))


def test_a_limit_frozen_unknown_session_is_rotated_and_told_to_continue_once(state):
    manager = Manager([info("cloude_a"), info("cloude_b")])
    rotation = Rotation()
    made = run(manager, state, rotation=rotation)
    assert [(r.tmux_session, r.from_account_id, r.to_account_id, r.ok) for r in made] == [("cloude_a", "old", "new", True)]
    assert manager.respawned == [("cloude_a", {
        "live_restart_confirmed": True, "require_agent_resume": True, "account_id": "new",
        "account_pinned": False, "persist_account": False, "live_restart_reason": "usage_limit_rotation",
    })]
    assert rotation.moved == [("old", "new")]
    assert rotation.pasted == [("id_cloude_a", "uuid-1")]
    assert rotation.notices == [("limit_rotated", "cloude_a", "old", "new", "weekly")]
    assert run(manager, state, rotation=rotation, clock=100.0 + 3600) == []
    assert len(manager.respawned) == 1 and len(rotation.pasted) == 1


def test_a_transient_429_does_nothing(tmp_path, monkeypatch, state):
    import json as _json

    from src.core.session_token_usage import claude_reader

    transient = {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit", "apiErrorIsTransient": True,
                 "uuid": "t1", "timestamp": "2026-09-25T10:00:00Z",
                 "message": {"content": [{"type": "text", "text": "API Error: Server is temporarily limiting requests (not your usage limit)"}]}}
    path = tmp_path / "c.jsonl"
    path.write_text("\n".join(_json.dumps(r) for r in [user_record(), transient]) + "\n")
    monkeypatch.setattr(claude_reader, "locate_transcript", lambda uuid, working_dir=None: SimpleNamespace(path=path))

    class Known(Manager):
        def _claude_uuid_for_tmux_name(self, name):
            return "conv"

    manager = Known([info("cloude_a")])
    rotation = Rotation()
    assert run(manager, state, rotation=rotation, evidence=auto_restart.SessionEvidence(manager)) == []
    assert manager.respawned == [] and rotation.pasted == []


def test_a_pinned_session_is_skipped_with_one_notification(state):
    manager = Manager([info("cloude_a")])
    rotation = Rotation(pinned="old")
    assert run(manager, state, rotation=rotation) == [] and run(manager, state, rotation=rotation) == []
    assert manager.respawned == [] and rotation.pasted == []
    assert rotation.notices == [("limit_pinned", "cloude_a", "old", "old", "weekly")]


def test_no_target_is_not_marked_and_acts_on_a_later_pass(state):
    manager = Manager([info("cloude_a")])
    rotation = Rotation()
    capped = LedgerSnapshot(accounts=[row("old", 100), row("new", 100)], total=LedgerTotal(accounts=2),
                            loop=LoopStatus(alive=True))
    assert run(manager, state, rotation=rotation, snap=capped) == [] and manager.respawned == []
    assert state.may_restart("rec-1") == (True, None)
    assert len(run(manager, state, rotation=rotation, clock=115.0)) == 1
    assert len(manager.respawned) == 1 and len(rotation.pasted) == 1


def test_a_body_restarted_after_the_record_gets_continue_only(state):
    manager = Manager([info("cloude_a", status="idle")])
    rotation = Rotation()
    assert run(manager, state, rotation=rotation, evidence=Evidence(started=STOP.timestamp + timedelta(minutes=5))) == []
    assert manager.respawned == [] and rotation.pasted == [("id_cloude_a", "uuid-1")]
    assert rotation.notices[0][0] == "limit_resumed"
    run(manager, state, rotation=rotation, evidence=Evidence(started=STOP.timestamp + timedelta(minutes=5)))
    assert len(rotation.pasted) == 1


def test_a_restarted_body_that_is_not_at_a_prompt_gets_nothing(state):
    manager = Manager([info("cloude_a", status="working")])
    rotation = Rotation()
    run(manager, state, rotation=rotation, evidence=Evidence(started=STOP.timestamp + timedelta(minutes=5)))
    assert rotation.pasted == [] and manager.respawned == []


def test_after_the_reset_the_session_restarts_in_place_on_its_own_account(state):
    manager = Manager([info("cloude_a")])
    rotation = Rotation()
    past = LimitStop("rec-1", NOW - timedelta(hours=1), NOW - timedelta(minutes=1), "five_hour")
    made = run(manager, state, rotation=rotation, evidence=Evidence(stop=past), read=profiles({}, after="/p/old"))
    assert [(r.from_account_id, r.to_account_id, r.ok) for r in made] == [("old", "old", True)]
    assert manager.respawned[0][1]["account_id"] == "old" and rotation.moved == []
    assert rotation.notices == [("limit_continued", "cloude_a", "old", "old", "session")]


def test_a_failed_paste_is_told_once_and_retried_as_continue_only(state):
    manager = Manager([info("cloude_a")])
    refusing = Rotation(refuse_paste=True)
    run(manager, state, rotation=refusing)
    assert refusing.pasted == [] and [n[0] for n in refusing.notices] == ["limit_failed"]
    assert not state.continue_sent("rec-1")
    manager.rows = [info("cloude_a", status="idle")]
    working = Rotation()
    run(manager, state, rotation=working, evidence=Evidence(started=STOP.timestamp + timedelta(minutes=5)), clock=200.0)
    assert working.pasted == [("id_cloude_a", "uuid-1")] and len(manager.respawned) == 1


@pytest.mark.parametrize("status,hint", [("dead", None), ("idle", "shell")])
def test_a_dead_pane_or_an_open_shell_command_is_never_restarted(state, status, hint):
    manager = Manager([info(status=status, hint=hint)])
    assert run(manager, state) == [] and manager.respawned == []


def test_a_stale_record_is_history(state):
    old = LimitStop("rec-1", NOW - timedelta(days=9), NOW - timedelta(days=8), "seven_day")
    manager = Manager([info()])
    assert run(manager, state, evidence=Evidence(stop=old)) == [] and manager.respawned == []


def test_off_by_default_nothing_restarts(state):
    manager = Manager([info()])
    assert run(manager, state, switch=ProviderAccountSwitchConfig(active_claude="new")) == []
    assert manager.respawned == []


def test_no_limit_evidence_means_no_restart(state):
    manager = Manager([info()])
    assert run(manager, state, evidence=Evidence(blocked=())) == [] and manager.respawned == []


def test_an_unreadable_pane_account_is_never_guessed(state):
    manager = Manager([info()])
    assert run(manager, state, read=profiles({"cloude_a": None})) == [] and manager.respawned == []


@pytest.mark.parametrize("state_name,pct", [("expired", 5), ("unknown", 5), ("ok", 100)])
def test_a_target_that_is_not_eligible_restarts_nothing(state, state_name, pct):
    snap = LedgerSnapshot(accounts=[row("old", 100), row("new", pct, state=state_name)],
                          total=LedgerTotal(accounts=2), loop=LoopStatus(alive=True))
    manager = Manager([info()])
    assert run(manager, state, snap=snap) == [] and manager.respawned == []


def test_a_target_a_session_cannot_start_and_resume_on_is_skipped(state):
    manager = Manager([info()])
    assert run(manager, state, rotation=Rotation(launchable=False)) == [] and manager.respawned == []


def test_a_conversation_that_would_not_resume_is_never_restarted(state):
    manager = Manager([info()])
    assert run(manager, state, evidence=Evidence(resumable=False)) == [] and manager.respawned == []


def test_a_pane_with_recent_output_is_never_restarted(state):
    manager = Manager([info()])
    assert run(manager, state, evidence=Evidence(quiet=auto_restart.QUIET_SECONDS - 1, stop=FRESH_STOP)) == []
    assert run(manager, state, evidence=Evidence(quiet=None, stop=FRESH_STOP)) == []
    assert manager.respawned == []


def test_a_repainting_limit_screen_is_restarted_once_the_stop_record_is_old_enough(state):
    from structlog.testing import capture_logs

    old_stop = LimitStop(uuid="rec-1", timestamp=NOW - timedelta(minutes=3), resets_at=NOW + timedelta(hours=2),
                         rate_limit_type="seven_day")
    held = Manager([info()])
    with capture_logs() as logs:
        assert run(held, state, evidence=Evidence(quiet=2.0, stop=FRESH_STOP)) == []
    assert held.respawned == [] and skips(logs) == [("cloude_a", "quiet_window")]

    manager = Manager([info()])
    assert run(manager, state, evidence=Evidence(quiet=2.0, stop=old_stop)) != [] and len(manager.respawned) == 1


def test_a_new_last_turn_before_the_kill_leaves_it_alone(state):
    other = LimitStop("rec-2", STOP.timestamp, STOP.resets_at, "seven_day")
    manager = Manager([info()])
    assert run(manager, state, evidence=Evidence(stops=[STOP, other])) == [] and manager.respawned == []


def test_turning_it_off_mid_pass_stops_the_kill(state):
    manager = Manager([info()])
    off = ProviderAccountSwitchConfig(auto_switch=False, active_claude="old")
    assert run(manager, state, fresh_switch=off) == [] and manager.respawned == []


def test_a_session_that_died_before_the_kill_is_left_alone(state):
    manager = Manager([info()], fresh_status="dead")
    assert run(manager, state) == [] and manager.respawned == []


def test_a_restart_that_did_not_change_the_account_is_failed_and_types_nothing(state):
    manager = Manager([info()])
    rotation = Rotation()
    made = run(manager, state, rotation=rotation, read=profiles({}, after="/p/old"))
    assert [r.ok for r in made] == [False] and rotation.pasted == []
    assert [n[0] for n in rotation.notices] == ["limit_failed"]


@pytest.mark.parametrize("result", [
    {"ok": True, "kind": "shell", "conversation": "resumed"},
    {"ok": True, "kind": "agent", "conversation": "fresh"},
    {"ok": False, "kind": "agent", "conversation": "resumed"},
])
def test_a_restart_that_did_not_resume_the_agent_is_not_ok(state, result):
    manager = Manager([info()], result=result)
    rotation = Rotation()
    assert [r.ok for r in run(manager, state, rotation=rotation)] == [False] and rotation.pasted == []


def test_a_pane_that_never_reaches_its_prompt_is_told_not_typed_into(state):
    manager = Manager([info()])
    rotation = Rotation(ready=False)
    run(manager, state, rotation=rotation)
    assert rotation.pasted == [] and [n[0] for n in rotation.notices] == ["limit_failed"]


def test_the_attempts_and_cooldown_survive_a_server_restart(tmp_path):
    clock = {"t": NOW.timestamp()}
    path = tmp_path / "s.json"
    first = RotationState(path, clock=lambda: clock["t"])
    first.record_attempt("rec-1")
    assert first.may_restart("rec-1") == (False, "cooldown")
    reborn = RotationState(path, clock=lambda: clock["t"])
    assert reborn.may_restart("rec-1") == (False, "cooldown")
    clock["t"] += 31 * 60
    assert reborn.may_restart("rec-1") == (True, None)
    reborn.record_attempt("rec-1")
    clock["t"] += 31 * 60
    assert RotationState(path, clock=lambda: clock["t"]).may_restart("rec-1") == (False, "attempts_exhausted")
    assert reborn.claim_notice("rec-1", "limit_failed") and not RotationState(path).claim_notice("rec-1", "limit_failed")


def test_codex_sessions_are_never_restarted(state):
    manager = Manager([info(family="codex")])
    assert run(manager, state) == [] and manager.respawned == []


def test_one_pass_at_a_time(state):
    manager = Manager([info()])
    auto_restart._RUNNING = True
    try:
        assert run(manager, state) == [] and manager.respawned == []
    finally:
        auto_restart._RUNNING = False


def test_at_most_a_bounded_number_per_pass(state):
    names = [f"cloude_{i}" for i in range(6)]

    class OwnRecord(Evidence):
        async def limit_stop(self, i):
            return LimitStop(f"rec-{i.tmux_session}", STOP.timestamp, STOP.resets_at, "seven_day")

    manager = Manager([info(n) for n in names])
    assert len(run(manager, state, evidence=OwnRecord(blocked=names))) == auto_restart.MAX_RESTARTS_PER_PASS


def test_the_pool_includes_the_built_in_default_login(state):
    from src.core.provider_ledger.poller_scan import AUTO_DEFAULT_ACCOUNT_ID

    builtin = ProviderAccount(id=AUTO_DEFAULT_ACCOUNT_ID, name="default", provider="claude", claude_config_dir="/p/builtin")
    snap = LedgerSnapshot(accounts=[row("old", 100), row(AUTO_DEFAULT_ACCOUNT_ID, 5)], total=LedgerTotal(accounts=2),
                          loop=LoopStatus(alive=True))
    manager = Manager([info()])
    made = run(manager, state, snap=snap, accounts=ACCOUNTS + [builtin], read=profiles({}, after="/p/builtin"))
    assert [(r.to_account_id, r.ok) for r in made] == [(AUTO_DEFAULT_ACCOUNT_ID, True)]




def test_the_real_evidence_refuses_an_unknown_conversation():

    class NoUuid:
        def _tmux_socket_name(self):
            return "unused"

        def _claude_uuid_for_tmux_name(self, name):
            return None

    assert asyncio.run(auto_restart.SessionEvidence(NoUuid()).limit_stop(info())) is None


def test_the_real_evidence_reads_the_transcript_tail(tmp_path, monkeypatch):
    import json as _json

    from src.core.session_token_usage import claude_reader

    path = tmp_path / "c.jsonl"
    stop = dict(limit_record(), uuid="stop-1", timestamp="2026-09-25T10:00:00Z")
    path.write_text("\n".join(_json.dumps(r) for r in [user_record(), stop, {"type": "system"}]) + "\n")
    monkeypatch.setattr(claude_reader, "locate_transcript",
                        lambda uuid, working_dir=None: SimpleNamespace(path=path))

    class Known:
        def _tmux_socket_name(self):
            return "unused"

        def _claude_uuid_for_tmux_name(self, name):
            return "conv"

    evidence = auto_restart.SessionEvidence(Known())
    found = asyncio.run(evidence.limit_stop(info()))
    assert (found.uuid, found.kind) == ("stop-1", "weekly")
    path.write_text(path.read_text() + _json.dumps(user_record("continue")) + "\n")
    assert asyncio.run(evidence.limit_stop(info())) is None


def test_a_limit_stop_with_no_id_is_not_acted_on(tmp_path, monkeypatch):
    import json as _json

    from src.core.session_token_usage import claude_reader

    stop = {k: v for k, v in limit_record().items() if k not in ("uuid", "timestamp")}
    assert limit_detect.transcript_blocked([stop])
    path = tmp_path / "c.jsonl"
    path.write_text(_json.dumps(user_record()) + "\n" + _json.dumps(stop) + "\n")
    monkeypatch.setattr(claude_reader, "locate_transcript",
                        lambda uuid, working_dir=None: SimpleNamespace(path=path))

    class Known:
        def _tmux_socket_name(self):
            return "unused"

        def _claude_uuid_for_tmux_name(self, name):
            return "conv"

    assert asyncio.run(auto_restart.SessionEvidence(Known()).limit_stop(info())) is None


def test_wait_ready_accepts_a_finished_unread_prompt():
    from src.core.session_delivery import bring_up

    class Ops:
        async def list(self):
            return [SimpleNamespace(activity_status="finished_unread", session=SimpleNamespace(id="s1"))]

        async def durable_keys(self, infos=None):
            return {}

    assert asyncio.run(bring_up.wait_ready(Ops(), lambda i, k: True, "x", timeout=1, step=0.01)) == "s1"




def skips(logs):
    return [(e["tmux_session"], e["gate"]) for e in logs if e["event"] == "auto_restart_skipped"]


def test_every_skipped_session_gets_one_line_naming_its_gate(state):
    from structlog.testing import capture_logs

    manager = Manager([info("cloude_w", status="dead"), info("cloude_q"), info("cloude_s", family="shell")])
    with capture_logs() as logs:
        run(manager, state, evidence=Evidence(blocked=("cloude_q",), quiet=30.0, stop=FRESH_STOP))
    assert skips(logs) == [("cloude_w", "dead_or_shell_open"), ("cloude_q", "quiet_window")]
    assert manager.respawned == []


def test_a_repeat_of_the_same_gate_is_throttled_and_a_new_gate_is_logged(state):
    from structlog.testing import capture_logs

    manager = Manager([info("cloude_q")])
    with capture_logs() as logs:
        run(manager, state, evidence=Evidence(blocked=("cloude_q",), quiet=30.0, stop=FRESH_STOP), clock=100.0)
        run(manager, state, evidence=Evidence(blocked=("cloude_q",), quiet=45.0, stop=FRESH_STOP), clock=115.0)
        run(manager, state, evidence=Evidence(blocked=()), clock=130.0)
        run(manager, state, evidence=Evidence(blocked=("cloude_q",), quiet=30.0, stop=FRESH_STOP), clock=145.0)
        run(manager, state, evidence=Evidence(blocked=("cloude_q",), quiet=30.0, stop=FRESH_STOP),
            clock=145.0 + auto_restart.SKIP_LOG_REPEAT_SECONDS + 1)
    assert skips(logs) == [
        ("cloude_q", "quiet_window"),
        ("cloude_q", "no_limit_stop"),
        ("cloude_q", "quiet_window"),
        ("cloude_q", "quiet_window"),
    ]


def _timer_run(manager, state, evidence_for_tick, ticks):
    from src.core.account_switch.restart_timer import RestartTimer

    snap = LedgerSnapshot(accounts=[row("old", 100), row("new", 5)],
                          total=LedgerTotal(accounts=2), loop=LoopStatus(alive=True))
    switch = ProviderAccountSwitchConfig(auto_switch=True, active_claude="old")
    count = {"n": 0}

    async def one_pass(snapshot, app_state):
        count["n"] += 1
        return await auto_restart.restart_blocked_sessions(
            manager, snapshot, ACCOUNTS, switch, now=NOW, monotonic=lambda: 100.0 + count["n"] * 15,
            evidence=evidence_for_tick(count["n"]), read_profile=profiles({}),
            current_switch=lambda: switch, rotation=Rotation(), state=state,
        )

    async def main():
        timer = RestartTimer(app_state=None, snapshot=lambda: snap, run_pass=one_pass, tick_seconds=0.01)
        assert timer.start() is True
        for _ in range(500):
            if count["n"] >= ticks:
                break
            await asyncio.sleep(0.01)
        await timer.stop()

    asyncio.run(main())
    return count["n"]


def test_the_timer_moves_a_limit_stopped_session_once_it_is_quiet(state):
    quiet = {1: 30.0, 2: 75.0}
    manager = Manager([info("cloude_a")])
    ran = _timer_run(manager, state, lambda n: Evidence(quiet=quiet.get(n, 600.0), stop=FRESH_STOP), ticks=5)
    assert ran >= 5
    assert [name for name, _ in manager.respawned] == ["cloude_a"]




def test_a_rotation_never_writes_or_clears_a_pin_through_the_real_persist_path(tmp_path, monkeypatch):
    import json as _json

    from src.core.account_switch import restart_account, session_pin

    config = tmp_path / "config.json"
    config.write_text(_json.dumps({session_pin.PINS_KEY: {"u1": "old"}}))
    monkeypatch.setattr(session_pin, "require_launchable", lambda path, account_id: None)

    async def go(persist: bool):
        plan = await restart_account.resolve(
            config, session_uuid="u1", family="claude", requested="new", pinned_box=False, persist=persist)
        return plan, await restart_account.persist(config, "u1", plan)

    plan, outcome = asyncio.run(go(False))
    assert (plan.account_id, outcome) == ("new", None)
    assert session_pin.read_pins(_json.loads(config.read_text())) == {"u1": "old"}
    assert asyncio.run(go(True))[1] == "cleared"
    assert session_pin.read_pins(_json.loads(config.read_text())) == {}


def test_the_pass_asks_for_a_rotation_that_leaves_pins_alone(state):
    manager = Manager([info("cloude_a")])
    run(manager, state)
    assert manager.respawned[0][1]["persist_account"] is False


def test_the_real_pin_read_tells_unreadable_from_absent(tmp_path):
    from src.core.account_switch import limit_rotate

    missing = limit_rotate.Rotation(None, lambda: tmp_path / "nope.json")
    with pytest.raises(limit_rotate.PinUnreadable):
        asyncio.run(missing.pin_for("u1"))
    good = tmp_path / "config.json"
    good.write_text("{}")
    assert asyncio.run(limit_rotate.Rotation(None, lambda: good).pin_for("u1")) is None


@pytest.mark.parametrize("how", ["no_key", "unreadable", "pinned_since"])
def test_a_session_whose_pin_cannot_be_proven_absent_is_never_restarted(state, how):
    from src.core.account_switch import limit_rotate

    manager = Manager([info("cloude_a")])
    rotation = Rotation()
    if how == "no_key":
        rotation.uuid = None
    elif how == "unreadable":
        rotation.pin_reads = [limit_rotate.PinUnreadable()]
    else:
        rotation.pin_reads = [None, "old"]
    assert run(manager, state, rotation=rotation) == []
    assert manager.respawned == [] and rotation.pasted == []


def test_two_capped_accounts_do_not_ping_pong(state):
    manager = Manager([info("cloude_a")])
    rotation = Rotation()
    assert len(run(manager, state, rotation=rotation)) == 1
    assert state.capped_accounts() == {"old"}
    later = STOP.__class__(uuid="rec-2", timestamp=NOW - timedelta(minutes=30), resets_at=NOW + timedelta(hours=2),
                           rate_limit_type="seven_day")
    lagging = LedgerSnapshot(accounts=[row("old", 5), row("new", 100)], total=LedgerTotal(accounts=2),
                             loop=LoopStatus(alive=True))
    assert run(manager, state, rotation=rotation, snap=lagging, evidence=Evidence(stop=later),
               read=profiles({"cloude_a": "/p/new"}), clock=100.0 + 3600) == []
    assert len(manager.respawned) == 1


def test_a_proven_cap_is_forgotten_once_it_resets(tmp_path):
    now = [NOW.timestamp()]
    st = RotationState(tmp_path / "s.json", clock=lambda: now[0])
    st.note_cap("old", now[0] + 60)
    assert st.capped_accounts() == {"old"}
    now[0] += 61
    assert st.capped_accounts() == set()


_WORDING = {
    "limit_rotated": ("session moved to another account", "and told to continue"),
    "limit_continued": ("session continued after its limit reset", "limit reset and told to continue"),
    "limit_resumed": ("session told to continue", "already restarted after a weekly usage limit"),
    "limit_pinned": ("usage limit, needs you", "pinned to its account, so it was left alone"),
    "limit_failed": ("usage limit rotation failed, needs you", "did not work"),
}


@pytest.mark.parametrize("outcome", list(_WORDING))
def test_every_outcome_reaches_destinations_once_with_its_own_words(monkeypatch, outcome):
    from src.core.account_switch import auto_switch, limit_rotate
    from src.core.notifications import contracts, copy
    from src.core.notifications.kind_specs import get_kind

    events = []
    monkeypatch.setattr(contracts, "emit", lambda ev: events.append(ev))
    monkeypatch.setattr(limit_rotate.session_change_notice, "publish", lambda app, frame: None)
    monkeypatch.setattr(auto_switch.session_change_notice, "publish", lambda app, frame: None)
    monkeypatch.setattr(auto_switch.resource_push, "notify", lambda topic: None)
    monkeypatch.setattr(limit_rotate.resource_push, "notify", lambda topic: None)
    limit_rotate.Rotation(None, lambda: None).notify(
        outcome, session="cloude_a", from_account_id="old", to_account_id="new", limit_kind="weekly", moved=True)
    assert [e.type_id for e in events] == ["session.limit_rotation"]
    rendered = copy.render(events[0], get_kind("slack"), details_on=True)
    title, phrase = _WORDING[outcome]
    assert rendered.title == title and phrase in rendered.body and "cloude_a" in rendered.body
    assert "account switched" not in rendered.title + rendered.body
    assert rendered.details == "old to new, weekly limit"


def test_rotated_body_names_both_accounts_and_the_limit_and_renders_cleanly_without_them():
    from src.core.notifications import copy
    from src.core.notifications.kind_specs import get_kind
    from src.core.notifications.sources import frames
    from src.core.notifications import contracts

    events = []
    real = contracts.emit
    contracts.emit = events.append
    try:
        frames.limit_rotation("rotated", session="Orchardco-2", from_account_id="a1", to_account_id="a2",
                              limit_kind="weekly", from_name="claude-acme", to_name="claude-code-work")
        frames.limit_rotation("rotated", session="Orchardco-2", from_account_id="", to_account_id="", limit_kind="other")
    finally:
        contracts.emit = real
    full = copy.render(events[0], get_kind("slack"), details_on=False).body
    assert full == ("Orchardco-2 hit its weekly limit on claude-acme, was moved to claude-code-work and told to continue.")
    bare = copy.render(events[1], get_kind("slack"), details_on=False).body
    assert bare == "Orchardco-2 hit its limit, was moved and told to continue."
    assert "None" not in bare and "{" not in bare and "[" not in bare


def test_a_config_that_is_not_an_object_is_an_unreadable_pin(tmp_path):
    from src.core.account_switch import limit_rotate

    bad = tmp_path / "config.json"
    bad.write_text("[]")
    with pytest.raises(limit_rotate.PinUnreadable):
        asyncio.run(limit_rotate.Rotation(None, lambda: bad).pin_for("u1"))


def test_a_rotation_whose_pointer_did_not_move_records_no_switch(monkeypatch):
    from src.core.account_switch import limit_rotate

    emitted, recorded = [], []
    monkeypatch.setattr(limit_rotate.frames, "limit_rotation", lambda outcome, **kw: emitted.append(outcome))
    monkeypatch.setattr(limit_rotate.session_change_notice, "publish", lambda app, frame: None)
    monkeypatch.setattr(limit_rotate, "record_switch", lambda app, **kw: recorded.append(kw))
    limit_rotate.Rotation(None, lambda: None).notify(
        "limit_rotated", session="s", from_account_id="a", to_account_id="b", limit_kind="weekly", moved=False)
    assert recorded == [] and len(emitted) == 1


def test_the_pass_tells_the_rotation_whether_the_pointer_moved(state):
    rotation = Rotation()
    run(Manager([info("cloude_a")]), state, rotation=rotation)
    assert rotation.moved_flags == [True]


def test_the_ledger_hook_does_not_wait_on_a_rotation(monkeypatch):
    from src.core.account_switch import auto_switch, ledger_hook, profile_setup

    gate = {}

    async def slow(snapshot, app_state=None):
        await gate["release"].wait()

    async def noop(snapshot, app_state=None):
        return None

    async def go():
        gate["release"] = asyncio.Event()
        monkeypatch.setattr(profile_setup, "after_pass", noop)
        monkeypatch.setattr(auto_switch, "after_pass", noop)
        monkeypatch.setattr(auto_restart, "after_pass", slow)
        await asyncio.wait_for(ledger_hook.after_ledger_pass(None, None), 1)
        assert len(ledger_hook._TASKS) == 1
        gate["release"].set()
        await asyncio.sleep(0.05)
        assert not ledger_hook._TASKS

    asyncio.run(go())


def test_the_rollout_baseline_skips_a_record_whose_reset_had_passed(tmp_path):
    fresh = RotationState(tmp_path / "limit_rotation.json", clock=lambda: NOW.timestamp())
    old = STOP.__class__(uuid="rec-old", timestamp=NOW - timedelta(days=2), resets_at=NOW - timedelta(days=1),
                         rate_limit_type="seven_day")
    manager = Manager([info("cloude_a")])
    assert run(manager, fresh, evidence=Evidence(stop=old)) == [] and manager.respawned == []
    assert fresh.baselined() and fresh.pre_existing("rec-old")
    assert run(manager, fresh, evidence=Evidence(stop=old), clock=100.0 + 3600) == []
    assert manager.respawned == []
    newer = STOP.__class__(uuid="rec-new", timestamp=NOW - timedelta(hours=2), resets_at=NOW - timedelta(hours=1),
                           rate_limit_type="seven_day")
    assert len(run(manager, fresh, evidence=Evidence(stop=newer), clock=100.0 + 7200)) == 1


def test_the_rollout_baseline_handles_a_record_still_in_force(tmp_path):
    fresh = RotationState(tmp_path / "limit_rotation.json", clock=lambda: NOW.timestamp())
    manager = Manager([info("cloude_a")])
    assert len(run(manager, fresh)) == 1 and fresh.baselined()


def test_the_baseline_survives_a_server_restart(tmp_path):
    path = tmp_path / "limit_rotation.json"
    first = RotationState(path, clock=lambda: NOW.timestamp())
    first.take_baseline({"gone": NOW.timestamp() - 10, "live": NOW.timestamp() + 10, "unknown": None})
    again = RotationState(path, clock=lambda: NOW.timestamp() + 30 * 24 * 3600)
    assert again.baselined() and again.pre_existing("gone")
    assert not again.pre_existing("live") and not again.pre_existing("unknown")
