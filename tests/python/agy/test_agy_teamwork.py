
from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_agytw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_agytw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.api.subagent_listing import mark_subagents
from src.core.agy.state import STATE_FOLDER, teamwork_active
from src.models import Session, SessionInfo

CONV = "11111111-2222-3333-4444-555555555555"


def _sub(name, status):
    return {"name": name, "role": "x", "status": status, "model": "Gemini 4 Neon (High)"}


def test_teamwork_running_lights_workflow_active_on_an_agy_row_only(tmp_path, monkeypatch):
    folder = tmp_path / STATE_FOLDER
    folder.mkdir()
    state = {"conversation_id": CONV, "agent_state": "idle",
             "subagents": [_sub("research", "completed"), _sub("teamwork_orchestrator", "running")]}
    (folder / "4242.json").write_text(json.dumps(state))
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path)
    monkeypatch.setattr("src.core.agy.identity.info_is_agy", lambda info, profiles=None: info.agent_family == "custom")

    def row(family):
        return SessionInfo(session=Session(id="ses_a", working_dir="/tmp"), agent_family=family, claude_session_uuid=CONV)

    agy, other = row("custom"), row("codex")
    mark_subagents(SimpleNamespace(_attention_watcher=None), [agy, other])
    assert agy.workflow_active is True
    assert other.workflow_active is None
    assert teamwork_active({"subagents": [_sub("teamwork_worker", "completed"), _sub("research", "running")]}) is False
    assert teamwork_active(None) is None
