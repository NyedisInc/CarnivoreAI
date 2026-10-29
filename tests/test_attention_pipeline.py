from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_attention_wiring import RecordingManager, no_real_pulls
from tests.test_codex_gather import THREAD, _make_codex_home
from src.core import attention_reader, session_change_notice, session_manager
from src.core.attention.display import to_display
from src.core.attention.registry_read import read_registry_index
from src.core.attention_wiring import build_attention_watcher
from src.core.session_status_map import StatusMap
from src.core.session_instance_index import InstanceIndex

SID = "ses_pipeline"
NAME = "cloude_pipeline"
EPOCH = 1789095742
ROOT = Path(__file__).resolve().parents[1]
CLAUDE_REST = "----------------\n❯\n----------------\n? for shortcuts"
CLAUDE_PERMISSION = "Bash command\n date\nDo you want to proceed?\n1. Yes\n2. No\nEsc to cancel · Tab to amend"
CODEX_PERMISSION = "Would you like to run the following command?\nYes, just this once"


class Pipeline:

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: str):
        self.now = datetime.now(timezone.utc)
        self.screen = CLAUDE_REST if family == "claude" else "Ask Codex to do anything"
        self.captures = []
        self.events = []
        self.registry_dir = tmp_path / "registry"
        self.registry_dir.mkdir()
        self.transcript = tmp_path / "claude.jsonl"
        self.transcript.write_text("", encoding="utf-8")
        self.manager = RecordingManager({SID: NAME}, {})
        self.manager._registry.sessions[SID] = SimpleNamespace(
            agent_type=family, agent_type_via_fingerprint=False, working_dir=str(tmp_path),
        )
        self.manager._instance_index_for_listing = lambda *, socket, names: InstanceIndex()
        self.manager._identity_for_instance = lambda name, epoch: {
            "agent_type": family, "agent_family": family, "agent_family_source": "launched",
        }
        self.manager._build_tmux_status_map = lambda: StatusMap({
            NAME: {"status": "idle", "pid": os.getpid(), "created_at_epoch": EPOCH},
        }, complete=True, socket="cloude")
        self.uuid = THREAD
        monkeypatch.setattr(attention_reader, "read_instance_row", lambda *args, **kwargs: {
            "claude_session_uuid": self.uuid, "working_dir": str(tmp_path),
        })
        monkeypatch.setattr(attention_reader, "read_registry_index", lambda: read_registry_index(
            directory=str(self.registry_dir),
        ))
        monkeypatch.setattr(session_manager, "_configured_wrappers", lambda: [])
        from src.core.session_token_usage import claude_reader
        monkeypatch.setattr(claude_reader, "locate_transcript", lambda *a, **k:
                            SimpleNamespace(path=self.transcript, detail="fixture",
                                            outcome="present"))
        monkeypatch.setattr(attention_reader.AttentionEvidenceReader, "_capture", staticmethod(self.capture))
        monkeypatch.setattr(session_change_notice, "publish_attention_status",
                            lambda *a, **kw: self.events.append(kw))
        if family == "codex":
            self.home, self.rollout = _make_codex_home(tmp_path)
            monkeypatch.setattr(attention_reader, "DEFAULT_CODEX_HOME", str(self.home))
            from src.core.attention import codex_gather, codex_stores
            with sqlite3.connect(self.home / "state_5.sqlite") as db:
                db.execute("UPDATE threads SET cwd = ?", (str(tmp_path),))
            monkeypatch.setattr(codex_gather, "writer_lock_live", lambda *a: True)
            monkeypatch.setattr(codex_stores, "_owned_writer_uuids",
                                lambda home, pids: {THREAD} if os.getpid() in pids else set())
            monkeypatch.setattr(attention_reader.AttentionEvidenceReader, "_process_parents",
                                lambda reader, now: {os.getpid(): os.getppid()})
        self.watcher = build_attention_watcher(self.manager)
        self.watcher._now = lambda: self.now

    def capture(self, socket: str, name: str, history: int = 0) -> str | None:
        self.captures.append((socket, name))
        return self.screen

    def claude(self, status: str, pending: int = 0) -> None:
        stamp = self.now - timedelta(seconds=30)
        (self.registry_dir / f"{os.getpid()}.json").write_text(json.dumps({
            "pid": os.getpid(), "status": status,
            "statusUpdatedAt": int(stamp.timestamp() * 1000),
            "sessionId": THREAD, "cwd": str(self.transcript.parent),
            "tmux": NAME + ":@0.%0", "version": "2.1.266",
        }), encoding="utf-8")
        records = [
            {"type": "user", "timestamp": (stamp - timedelta(seconds=20)).isoformat(),
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "toolu_old_agent",
                  "content": "launched"}]},
             "toolUseResult": {"isAsync": True, "agentId": "old_agent"}},
            {"type": "assistant", "timestamp": (stamp - timedelta(seconds=10)).isoformat(),
             "message": {"content": [{"type": "text", "text": "finished"}]}},
            {"type": "system", "subtype": "turn_duration", "timestamp": stamp.isoformat(),
             "pendingBackgroundAgentCount": pending, "version": "2.1.266"},
        ]
        self.transcript.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")

    def codex(self, status: str) -> None:
        event = {"inProgress": "task_started", "interrupted": "turn_aborted"}.get(
            status, "task_complete",
        )
        self.rollout.write_text(json.dumps({
            "timestamp": self.now.isoformat(), "ordinal": 0, "type": "event_msg",
            "payload": {"type": event, "turn_id": "t0"},
        }) + "\n", encoding="utf-8")
        with sqlite3.connect(self.home / "thread_history_1.sqlite") as db:
            db.execute("UPDATE thread_turns SET status = ?", (status,))
            db.execute("DELETE FROM thread_history_projection_state")
            db.execute("INSERT INTO thread_history_projection_state VALUES (?, ?, 1)",
                       (THREAD, self.rollout.stat().st_size))

    def tick(self) -> object:
        self.now += timedelta(seconds=2)
        asyncio.run(self.watcher.tick_once())
        observation = self.watcher.observation_for(SID)
        assert observation is not None
        return observation

    def led(self) -> dict:
        observation = self.watcher.observation_for(SID)
        unread = bool(self.manager.unread_writes)
        row = {"activity_status": to_display(observation.verdict, unread=unread, tmux_status="idle"),
               "unread": unread}
        result = subprocess.run(["node", str(ROOT / "tests/helpers/led_state_for.mjs")],
                                input=json.dumps(row), text=True, capture_output=True, check=True)
        return json.loads(result.stdout)


def test_claude_zero_boundary_repairs_stale_green_without_startup_toast(tmp_path, monkeypatch, no_real_pulls):
    run = Pipeline(tmp_path, monkeypatch, "claude")
    run.claude("idle")
    observation = run.tick()
    assert observation.evidence.transcript.open_async_agents == 0
    assert observation.verdict.state == "done_idle"
    assert run.led()["inner"] == "idle"
    run.tick()
    assert run.manager.toasts == []
    assert len(run.captures) == 2


@pytest.mark.parametrize("pending", [0, 2])
def test_claude_idle_registry_cannot_hide_permission_or_dismiss_it(tmp_path, monkeypatch, no_real_pulls, pending):
    run = Pipeline(tmp_path, monkeypatch, "claude")
    run.claude("idle", pending)
    run.screen = CLAUDE_PERMISSION
    assert run.tick().verdict.state == "needs_user"
    run.tick()
    run.tick()
    assert [toast.kind for toast in run.manager.toasts] == ["PermissionRequest"]
    assert run.led()["inner"] == "waiting-permission"
    assert run.manager.acks == []
    run.screen = None
    assert run.tick().verdict.state == "unknown"
    assert [toast.kind for toast in run.manager.toasts] == ["PermissionRequest"]
    assert run.manager.acks == []


@pytest.mark.parametrize("end_status", ["completed", "interrupted"])
def test_codex_work_permission_work_completion_uses_one_observation(tmp_path, monkeypatch, no_real_pulls, end_status):
    run = Pipeline(tmp_path, monkeypatch, "codex")
    run.codex("completed")
    assert run.tick().verdict.state == "done_idle"
    assert run.manager.toasts == []
    run.codex("inProgress")
    run.screen = "working (2s · esc to interrupt)"
    assert run.tick().verdict.state == "busy"
    assert run.led()["inner"] == "working"
    run.screen = CODEX_PERMISSION
    run.tick()
    run.tick()
    run.tick()
    assert run.led()["inner"] == "waiting-permission"
    assert [toast.kind for toast in run.manager.toasts] == ["PermissionRequest"]
    run.screen = "working (3s · esc to interrupt)"
    assert run.tick().verdict.state == "busy"
    run.codex(end_status)
    run.screen = "Ask Codex to do anything"
    assert run.tick().verdict.state == "done_idle"
    run.tick()
    assert [toast.kind for toast in run.manager.toasts] == ["PermissionRequest", "Stop"]
    assert run.led() == {"inner": "done", "outer": "unread"}
    assert len(run.captures) == 8


def test_muted_codex_still_publishes_work_permission_and_unknown(tmp_path, monkeypatch, no_real_pulls):
    run = Pipeline(tmp_path, monkeypatch, "codex")
    run.manager._notification_policy_store = object()
    run.manager.notification_policy_stamp = lambda sid: SimpleNamespace(
        suppresses=True, verdict="muted", generation=1,
    )
    run.watcher = build_attention_watcher(run.manager)
    run.watcher._now = lambda: run.now
    run.codex("inProgress")
    run.screen = "working (2s · esc to interrupt)"
    run.tick()
    run.screen = CODEX_PERMISSION
    run.tick()
    run.tick()
    run.screen = None
    run.tick()
    assert run.manager.toasts == []
    assert [event["activity_status"] for event in run.events] == [
        "working", "question", "unknown",
    ]
    assert run.led()["inner"] == "unknown"


def test_muted_completion_publishes_unread_after_quiet_gate(tmp_path, monkeypatch, no_real_pulls):
    run = Pipeline(tmp_path, monkeypatch, "codex")
    run.manager._notification_policy_store = object()
    run.manager.notification_policy_stamp = lambda sid: SimpleNamespace(
        suppresses=True, verdict="muted", generation=1,
    )
    run.manager._is_unread = lambda name, epoch: bool(run.manager.unread_writes)
    run.watcher = build_attention_watcher(run.manager)
    run.watcher._now = lambda: run.now
    run.codex("inProgress")
    run.screen = "working (2s · esc to interrupt)"
    run.tick()
    run.codex("completed")
    run.screen = "Ask Codex to do anything"
    asyncio.run(run.watcher.tick_once())
    assert run.events[-1]["activity_status"] == "idle"
    assert run.manager.unread_writes == []
    run.tick()
    run.tick()
    assert run.manager.toasts == []
    assert run.events[-1]["activity_status"] == "finished_unread"


def test_codex_subagent_delivery_cannot_acknowledge_completion(tmp_path, monkeypatch, no_real_pulls):
    run = Pipeline(tmp_path, monkeypatch, "codex")
    run.codex("inProgress")
    run.screen = "working (2s · esc to interrupt)"
    run.tick()
    run.codex("completed")
    run.screen = "Ask Codex to do anything"
    run.tick()
    run.tick()
    assert [toast.kind for toast in run.manager.toasts] == ["Stop"]
    acks, work = list(run.manager.acks), list(run.manager.work_stamps)
    with run.rollout.open("a") as stream:
        stream.write(json.dumps({
            "timestamp": run.now.isoformat(), "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "<subagent_notification>done</subagent_notification>"},
            ]},
        }) + "\n")
    observation = run.tick()
    assert observation.new_user_prompt_at is None
    assert run.manager.acks == acks
    assert run.manager.work_stamps == work


@pytest.mark.parametrize("end_status", ["completed", "interrupted"])
def test_codex_permission_directly_to_rest_acknowledges_old_ask(tmp_path, monkeypatch, no_real_pulls, end_status):
    from src.core.toast_auto_ack import resolve_auto_acks

    run = Pipeline(tmp_path, monkeypatch, "codex")

    def acknowledge(session_id: str, event_kind: str, cutoff: datetime | None = None) -> list[str]:
        ids = resolve_auto_acks(run.manager.toasts, event_kind, cutoff=cutoff)
        for toast in run.manager.toasts:
            if toast.id in ids:
                toast.acknowledged = True
        return ids

    run.manager.auto_ack_toasts = acknowledge
    run.codex("inProgress")
    run.screen = CODEX_PERMISSION
    run.tick()
    run.tick()
    assert len(run.manager.toasts) == 1
    permission = run.manager.toasts[0]
    assert permission.kind == "PermissionRequest"
    assert permission.acknowledged is False
    run.codex(end_status)
    run.screen = "Ask Codex to do anything"
    assert run.tick().verdict.state == "done_idle"
    run.tick()
    assert permission.acknowledged is True
    assert [(toast.kind, toast.acknowledged) for toast in run.manager.toasts] == [
        ("PermissionRequest", True), ("Stop", False),
    ]
