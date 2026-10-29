
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_aw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_aw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import listing_attention  # noqa: E402
from src.core.attention import side_effects as side_effects_module  # noqa: E402
from src.core.attention.registry_read import parse_registry_record  # noqa: E402
from src.core.attention.transcript_facts import (  # noqa: E402
    FACTS_FOUND,
    TranscriptFacts,
)
from src.core.attention.watcher import AttentionWatcher, WatchTarget  # noqa: E402
from src.core.attention_wiring import build_attention_watcher  # noqa: E402
from src.core.event_hub import EventHub  # noqa: E402
from src.core.session_activity import EVENT_STOP  # noqa: E402
from src.core.sessions.toast_inbox import ToastInbox  # noqa: E402
from src.models import Toast  # noqa: E402
from src.core.session_status import (  # noqa: E402
    LIVENESS_LIVE,
    STATUS_IDLE,
    STATUS_UNKNOWN,
)
from src.core.session_status_map import StatusMap  # noqa: E402
from src.core.session_instance_index import InstanceIndex  # noqa: E402
from src.core.session_startup_gate_ledger import StartupGateLedger  # noqa: E402

SOCKET = "cloude"
EPOCH = 1789095742

WATCHER_COROUTINE = "AttentionWatcher.run"




def _watcher_tasks():
    return [
        task
        for task in asyncio.all_tasks()
        if getattr(task.get_coro(), "__qualname__", "") == WATCHER_COROUTINE
    ]


async def _boot_then_shut_down():
    from src.core.notifications import contracts, engine as notify_engine
    from src.main import app, lifespan

    async with lifespan(app):
        notify_wired = contracts.sink_installed() and notify_engine.current_engine() is not None
        created = _watcher_tasks()
        alive_during_boot = [task for task in created if not task.done()]
        watcher = getattr(app.state, "attention_watcher", None)
    return {
        "notify_wired_during_boot": notify_wired,
        "notify_tasks_left": [
            t for t in asyncio.all_tasks()
            if not t.done() and "NotifyEngine" in getattr(t.get_coro(), "__qualname__", "")
        ],
        "notify_unwired_at_exit": not contracts.sink_installed() and notify_engine.current_engine() is None,
        "created": created,
        "alive_during_boot": alive_during_boot,
        "watcher": watcher,
        "done_at_exit": [task.done() for task in created],
        "cancelled_at_exit": [task.cancelled() for task in created],
        "still_running": [task for task in _watcher_tasks() if not task.done()],
    }


def test_the_boot_creates_the_watcher_task_and_the_shutdown_cancels_it(monkeypatch, tmp_path):
    from src.config import settings

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(settings, "_auth_config_cache", None)
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path / "state"))
    facts = asyncio.run(_boot_then_shut_down())

    assert len(facts["created"]) == 1, (
        "lifespan must create exactly one attention watcher task; found %d"
        % len(facts["created"])
    )
    assert len(facts["alive_during_boot"]) == 1, (
        "the watcher task must still be running while the app is up"
    )
    assert isinstance(facts["watcher"], AttentionWatcher)
    assert facts["done_at_exit"] == [True], (
        "shutdown must not leave the watcher task running"
    )
    assert facts["cancelled_at_exit"] == [True], (
        "the watcher must end by CANCELLATION, not by returning or raising"
    )
    assert facts["still_running"] == []
    assert facts["notify_wired_during_boot"] and facts["notify_unwired_at_exit"]
    assert facts["notify_tasks_left"] == []




class RecordingManager:

    def publish_status_map(self, status_map) -> None:
        self.published_status_maps.append(status_map)

    def __init__(self, names: dict, reads: dict) -> None:
        self._names = dict(names)
        self._reads = dict(reads)
        self.published_status_maps: list = []
        self._registry = types.SimpleNamespace(
            sessions={sid: object() for sid in names},
            listable_ids=lambda: list(names),
            backends={
                sid: types.SimpleNamespace(
                    tmux_session=name, socket_name=SOCKET
                )
                for sid, name in names.items()
            },
        )
        self.hook_tokens = types.SimpleNamespace(
            name_for=lambda sid: self._names.get(sid)
        )
        self._instance_epochs = {sid: EPOCH for sid in names}
        self._startup_gate_ledger = StartupGateLedger()
        self._unread_store = types.SimpleNamespace(set_flag=self._set_flag)
        self._notification_policy_store = None
        self.unread_writes: list = []
        self.state_writes: list = []
        self.work_stamps: list = []
        self.acks: list = []
        self.toasts: list = []
        self._toast_inbox = ToastInbox()
        self.status_map_builds: int = 0


    def _instance_index_for_listing(self, *, socket, names):
        return InstanceIndex()

    def _tmux_socket_name(self):
        return SOCKET

    def _identity_for_instance(self, tmux_name, epoch):
        return {"agent_type": "claude", "agent_family": "claude",
                "agent_family_source": "launched"}

    def _build_tmux_status_map(self):
        self.status_map_builds += 1
        return StatusMap(
            {name: {"status": STATUS_IDLE} for name in self._names.values()},
            complete=True,
            socket=SOCKET,
        )


    def _set_flag(self, tmux_name, field_name, value, epoch=None):
        self.unread_writes.append((tmux_name, field_name, value, epoch))

    def _unread_epoch(self, tmux_name):
        return EPOCH

    def _persist_settled_activity_state(self, tmux_name, state, epoch):
        self.state_writes.append((tmux_name, state, epoch))

    def _persist_work_stamp(self, session_id, tmux_name, kind):
        self.work_stamps.append((session_id, tmux_name, kind))

    def auto_ack_toasts(self, session_id, event_kind, cutoff=None):
        self.acks.append((session_id, event_kind, cutoff))
        return []

    def record_toast(self, session_id, kind, title, body=None, *, notify_type=None):
        toast, _superseded = self._toast_inbox.store(
            session_id, kind=kind, title=title, body=body, color=None,
            session_label=None, session_name=None, notify_type=notify_type,
        )
        assert isinstance(toast, Toast)
        self.toasts.append(toast)
        return toast

    def notification_policy_stamp(self, session_id):
        return None


@pytest.fixture(autouse=True)
def gathered_file_tiers(monkeypatch, request):
    if request.node.name == "test_the_boot_creates_the_watcher_task_and_the_shutdown_cancels_it":
        return
    from src.core import attention_reader

    def read_row(manager, name, epoch, **kwargs):
        return {"claude_session_uuid": manager._reads[name]}

    def read_tiers(name, *, claude_session_uuid, **kwargs):
        if isinstance(claude_session_uuid, BaseException):
            raise claude_session_uuid
        return claude_session_uuid

    monkeypatch.setattr(attention_reader, "read_instance_row", read_row)
    monkeypatch.setattr(attention_reader, "attention_reads_for_name", read_tiers)
    monkeypatch.setattr(attention_reader, "read_registry_index", lambda: {})
    monkeypatch.setattr(attention_reader.AttentionEvidenceReader, "_capture",
                        staticmethod(lambda socket, name: None))


@pytest.fixture()
def no_real_pulls(monkeypatch):
    calls = {"infer": [], "title": []}
    monkeypatch.setattr(
        side_effects_module.session_agent_infer_apply,
        "apply_agent_inference",
        lambda manager, session_id, tmux_name: calls["infer"].append(session_id),
    )
    monkeypatch.setattr(
        side_effects_module.claude_title_sync_apply,
        "sync_claude_title",
        lambda manager, session_id: (
            calls["title"].append(session_id)
            or types.SimpleNamespace(broadcast_title=None)
        ),
    )
    return calls


def registry(status: str, *, at: datetime = None):
    at = at if at is not None else datetime.now(timezone.utc)
    return parse_registry_record(
        {
            "pid": 4242,
            "status": status,
            "statusUpdatedAt": int(at.timestamp() * 1000),
            "sessionId": "11111111-2222-3333-4444-555555555555",
            "cwd": "/tmp",
            "tmux": "cloude_a:@0.%0",
            "version": "2.1.266",
        },
        path_pid=4242,
    )


def busy_pair(*, at: datetime = None):
    at = at if at is not None else datetime.now(timezone.utc)
    return (
        registry("busy", at=at - timedelta(seconds=5)),
        TranscriptFacts(
            verdict=FACTS_FOUND,
            newest_append_at=at - timedelta(seconds=1),
            newest_assistant_at=at - timedelta(seconds=1),
        ),
    )


def done_pair(*, at: datetime = None, prompt_at: datetime = None):
    at = at if at is not None else datetime.now(timezone.utc)
    return (
        registry("idle", at=at - timedelta(seconds=5)),
        TranscriptFacts(
            verdict=FACTS_FOUND,
            turn_end_at=at - timedelta(seconds=30),
            newest_assistant_at=at - timedelta(seconds=40),
            newest_append_at=at - timedelta(seconds=30),
            newest_user_prompt_at=prompt_at,
            pending_background_agents=0,
            pending_field_present=True,
        ),
    )




def test_a_failing_evidence_read_costs_one_session_and_not_the_others(
    no_real_pulls,
):
    manager = RecordingManager(
        {"ses_bad": "cloude_bad", "ses_ok": "cloude_ok"},
        {
            "cloude_bad": OSError("the registry directory went away"),
            "cloude_ok": done_pair(),
        },
    )
    watcher = build_attention_watcher(manager, tick_seconds=0.0)

    async def drive():
        await watcher.tick_once()
        manager._reads["cloude_ok"] = busy_pair()
        return await watcher.tick_once()

    acted = asyncio.run(drive())

    assert acted == 1, "the healthy session's edge must still have been acted on"
    assert {write[0] for write in manager.state_writes} == {"cloude_ok"}
    assert manager.work_stamps == [("ses_ok", "cloude_ok", None)]


def test_a_failing_read_does_not_stop_the_loop_ticking():

    async def drive():
        manager = RecordingManager({"ses_a": "cloude_a"}, {"cloude_a": busy_pair()})
        watcher = build_attention_watcher(manager, tick_seconds=0.0)
        ticks = {"n": 0}
        original = watcher.tick_once

        async def counting_tick():
            ticks["n"] += 1
            if ticks["n"] == 1:
                raise RuntimeError("the first pass blew up")
            return await original()

        watcher.tick_once = counting_tick
        task = asyncio.create_task(watcher.run())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if ticks["n"] >= 3:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return ticks["n"], manager.state_writes

    ticks, state_writes = asyncio.run(drive())

    assert ticks >= 3, "the loop stopped after the tick that raised"
    assert state_writes, "no session was resolved after the failed tick"




def test_the_running_task_keeps_listing_its_targets():

    async def drive():
        manager = RecordingManager({"ses_a": "cloude_a"}, {"cloude_a": busy_pair()})
        watcher = build_attention_watcher(manager, tick_seconds=0.0)
        task = asyncio.create_task(watcher.run())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if manager.status_map_builds >= 3:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return manager.status_map_builds, task

    builds, task = asyncio.run(drive())

    assert builds >= 3, "the watcher task did not tick repeatedly"
    assert task.cancelled()


def test_one_bulk_tmux_listing_is_taken_per_pass_not_per_session():
    names = {"ses_%d" % i: "cloude_%d" % i for i in range(14)}
    manager = RecordingManager(
        names, {name: busy_pair() for name in names.values()}
    )
    watcher = build_attention_watcher(manager, tick_seconds=0.0)

    asyncio.run(watcher.tick_once())

    assert manager.status_map_builds == 1
    assert len(manager.state_writes) == 14, "every session must still be read"




def test_the_production_build_fires_every_job_the_hook_route_carried(
    no_real_pulls,
):

    async def drive():
        manager = RecordingManager(
            {"ses_a": "cloude_a"}, {"cloude_a": done_pair()}
        )
        watcher = build_attention_watcher(manager, tick_seconds=0.0)
        await watcher.tick_once()
        manager._reads["cloude_a"] = busy_pair()
        await watcher.tick_once()
        manager._reads["cloude_a"] = done_pair()
        await watcher.tick_once()
        return manager

    manager = asyncio.run(drive())

    assert manager._startup_gate_ledger.first_hook_at("cloude_a") is not None
    assert no_real_pulls["infer"] == ["ses_a"] * 3
    assert manager.unread_writes == [("cloude_a", "auto", True, EPOCH)]
    assert [write[0] for write in manager.state_writes] == ["cloude_a"] * 3
    assert manager.work_stamps == [("ses_a", "cloude_a", None)]
    assert [(ack[0], ack[1]) for ack in manager.acks] == [
        ("ses_a", "PreToolUse"), ("ses_a", "Stop"),
    ]
    assert no_real_pulls["title"], "the /rename pull never ran"
    assert [toast.kind for toast in manager.toasts] == [EVENT_STOP]


def test_the_sort_key_is_not_written_when_nothing_says_the_session_worked(
    no_real_pulls,
):

    async def drive():
        manager = RecordingManager(
            {"ses_a": "cloude_a"}, {"cloude_a": done_pair()}
        )
        watcher = build_attention_watcher(manager, tick_seconds=0.0)
        await watcher.tick_once()
        await watcher.tick_once()
        return manager

    manager = asyncio.run(drive())

    assert manager.work_stamps == []
    assert manager.state_writes, "the reading itself must still have happened"




def test_one_transition_raises_one_toast_while_the_listing_resolves_it_too(
    no_real_pulls,
):

    async def drive():
        at = datetime.now(timezone.utc)
        registry_record, transcript = done_pair(at=at)
        manager = RecordingManager(
            {"ses_a": "cloude_a"}, {"cloude_a": done_pair()}
        )
        watcher = build_attention_watcher(manager, tick_seconds=0.0)
        await watcher.tick_once()
        manager._reads["cloude_a"] = busy_pair()
        await watcher.tick_once()

        painted = []
        manager._reads["cloude_a"] = (registry_record, transcript)
        for _ in range(4):
            painted.append(
                listing_attention.resolve_row_status(
                    registry=registry_record,
                    transcript=transcript,
                    tmux_liveness=LIVENESS_LIVE,
                    agent_family=None,
                    pane=None,
                    unread=True,
                    tmux_status=STATUS_UNKNOWN,
                    now=at,
                )
            )
            await watcher.tick_once()
        return manager, painted

    manager, painted = asyncio.run(drive())

    assert len(manager.toasts) == 1, (
        "a session that stays finished must be announced once, not once per pass"
    )
    assert manager.toasts[0].kind == EVENT_STOP
    assert manager.toasts[0].notify_type == "session.finished"
    assert {status for status, _source, _hint in painted} == {"finished_unread"}
    assert {source for _status, source, _hint in painted} == {"registry"}
    assert {hint for _status, _source, hint in painted} == {None}


def test_a_toast_body_never_carries_the_resolvers_own_diagnostic(no_real_pulls):

    async def drive():
        manager = RecordingManager(
            {"ses_a": "cloude_a"}, {"cloude_a": done_pair()}
        )
        watcher = build_attention_watcher(manager, tick_seconds=0.0)
        await watcher.tick_once()
        manager._reads["cloude_a"] = busy_pair()
        await watcher.tick_once()
        manager._reads["cloude_a"] = done_pair()
        await watcher.tick_once()
        return manager

    manager = asyncio.run(drive())

    assert manager.toasts, (
        "no toast was raised, so every assertion below would pass by "
        "looking at nothing"
    )
    for toast in manager.toasts:
        assert toast.body is None, (
            "a toast card carried %r as its body. That is the resolver's "
            "own audit sentence, which belongs in the log." % (toast.body,)
        )




async def _finish_a_session(manager):
    watcher = build_attention_watcher(manager, tick_seconds=0.0)
    await watcher.tick_once()
    manager._reads["cloude_a"] = busy_pair()
    await watcher.tick_once()
    manager._reads["cloude_a"] = done_pair()
    await watcher.tick_once()


def _muteable_manager(*, suppresses: bool):
    manager = RecordingManager({"ses_a": "cloude_a"}, {"cloude_a": done_pair()})
    manager._notification_policy_store = object()
    manager.notification_policy_stamp = lambda session_id: types.SimpleNamespace(
        suppresses=suppresses, verdict="muted" if suppresses else "unmuted",
        generation=1,
    )
    return manager


def test_a_muted_session_gets_no_toast_but_still_gets_its_unread_flag(
    no_real_pulls,
):
    manager = _muteable_manager(suppresses=True)

    asyncio.run(_finish_a_session(manager))

    assert manager.toasts == []
    assert manager.unread_writes == [("cloude_a", "auto", True, EPOCH)]


def test_an_unmuted_session_with_a_policy_store_attached_still_gets_its_toast(
    no_real_pulls,
):
    manager = _muteable_manager(suppresses=False)

    asyncio.run(_finish_a_session(manager))

    assert [toast.kind for toast in manager.toasts] == [EVENT_STOP]




def _reader_with_recorded_captures(monkeypatch, reads):
    from src.core.attention_wiring import AttentionEvidenceReader

    taken: list = []

    def fake_capture(socket, name, history=0):
        taken.append(name)
        return "\n".join(["─" * 40, "❯ ", "─" * 40])

    monkeypatch.setattr(
        AttentionEvidenceReader, "_capture", staticmethod(fake_capture)
    )
    manager = RecordingManager({"ses_a": "cloude_a"}, reads)
    manager._build_tmux_status_map = lambda: StatusMap(
        rows={"cloude_a": {"status": "running", "pid": 1}},
        complete=True,
        socket=SOCKET,
    )
    reader = AttentionEvidenceReader(manager, lambda sid: ("cloude_a", EPOCH))
    return (reader, taken)


def test_a_busy_session_costs_one_pane_capture(monkeypatch):
    at = datetime.now(timezone.utc)
    reader, taken = _reader_with_recorded_captures(
        monkeypatch, {"cloude_a": busy_pair(at=at)}
    )
    evidence = reader(WatchTarget(session_id="ses_a", key="cloude_a@1"), at)

    assert taken == ["cloude_a"], "a busy session must be looked at"
    assert evidence.pane is not None
    assert evidence.pane.resting_prompt is True, evidence.pane.detail


def test_a_session_at_rest_still_gets_a_pane_capture(monkeypatch):
    at = datetime.now(timezone.utc)
    reader, taken = _reader_with_recorded_captures(
        monkeypatch, {"cloude_a": done_pair(at=at)}
    )
    evidence = reader(WatchTarget(session_id="ses_a", key="cloude_a@1"), at)

    assert taken == ["cloude_a"]
    assert evidence.pane.resting_prompt is True


def test_a_capture_that_could_not_run_leaves_the_pane_unstated(monkeypatch):
    from src.core.attention_wiring import AttentionEvidenceReader

    at = datetime.now(timezone.utc)
    monkeypatch.setattr(
        AttentionEvidenceReader,
        "_capture",
        staticmethod(lambda socket, name: None),
    )
    manager = RecordingManager({"ses_a": "cloude_a"}, {"cloude_a": busy_pair(at=at)})
    manager._build_tmux_status_map = lambda: StatusMap(
        rows={"cloude_a": {"status": "running", "pid": 1}},
        complete=True,
        socket=SOCKET,
    )
    reader = AttentionEvidenceReader(manager, lambda sid: ("cloude_a", EPOCH))
    evidence = reader(WatchTarget(session_id="ses_a", key="cloude_a@1"), at)

    assert evidence.pane is None




class _RecordingHub(EventHub):

    def __init__(self) -> None:
        super().__init__()
        self.frames: list = []

    def publish(self, frame) -> int:
        self.frames.append(frame)
        return super().publish(frame)


def _rename_wires(pulled_title):
    hub = _RecordingHub()
    app_state = types.SimpleNamespace(event_hub=hub)
    sent: list = []

    async def broadcast(session_id, payload):
        sent.append((session_id, payload))

    async def drive():
        manager = RecordingManager({"ses_a": "cloude_a"}, {"cloude_a": busy_pair()})
        watcher = build_attention_watcher(
            manager, app_state=app_state, broadcast=broadcast, tick_seconds=0.0
        )
        await watcher.tick_once()

    asyncio.run(drive())
    return sent, hub


def test_a_rename_typed_inside_claude_goes_out_on_both_wires(monkeypatch):
    monkeypatch.setattr(
        side_effects_module.session_agent_infer_apply,
        "apply_agent_inference",
        lambda manager, session_id, tmux_name: None,
    )
    monkeypatch.setattr(
        side_effects_module.claude_title_sync_apply,
        "sync_claude_title",
        lambda manager, session_id: types.SimpleNamespace(
            broadcast_title="Image Tool"
        ),
    )

    sent, hub = _rename_wires("Image Tool")

    renamed = [
        json.loads(payload)
        for _, payload in sent
        if json.loads(payload).get("type") == "session.renamed"
    ]
    assert len(renamed) == 1, "the terminal socket did not carry the rename"
    assert renamed[0]["new_name"] == "Image Tool"

    notices = [f for f in hub.frames if f.get("type") == "session.renamed"]
    assert len(notices) == 1, (
        "a /rename typed inside claude put %d notices on /ws/events, "
        "expected 1. Zero means every compiled terminal cell keeps the "
        "old name for as long as the terminal screen is up, because that "
        "screen pauses the listing poll those cells read their name from."
        % len(notices)
    )
    assert notices[0] == renamed[0], (
        "the two wires describe the same rename differently, so a client "
        "cannot keep one handler for both"
    )


def test_a_pull_that_found_no_new_name_announces_nothing(monkeypatch):
    monkeypatch.setattr(
        side_effects_module.session_agent_infer_apply,
        "apply_agent_inference",
        lambda manager, session_id, tmux_name: None,
    )
    monkeypatch.setattr(
        side_effects_module.claude_title_sync_apply,
        "sync_claude_title",
        lambda manager, session_id: types.SimpleNamespace(broadcast_title=None),
    )

    sent, hub = _rename_wires(None)

    assert [p for _, p in sent if "session.renamed" in p] == []
    assert [f for f in hub.frames if f.get("type") == "session.renamed"] == []


def test_every_observation_reaches_the_died_tracker(monkeypatch, no_real_pulls):
    from src.core.notifications.sources import died

    seen = []
    monkeypatch.setattr(died.DiedTracker, "observe", lambda self, target, observation: seen.append(target.session_id))

    async def drive():
        manager = RecordingManager({"ses_a": "cloude_a"}, {"cloude_a": done_pair()})
        watcher = build_attention_watcher(manager, tick_seconds=0.0)
        await watcher.tick_once()
        await watcher.tick_once()

    asyncio.run(drive())
    assert seen == ["ses_a", "ses_a"]
