
from __future__ import annotations

import json

import pytest

from src.core.swarm import launch, resume_agent

CONV = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class _Presence:
    def __init__(self, path):
        self.path = path


@pytest.fixture()
def transcript(tmp_path, monkeypatch):
    path = tmp_path / f"{CONV}.jsonl"
    monkeypatch.setattr("src.core.session_transcript_presence.conversation_presence",
                        lambda uuid, working_dir=None: _Presence(path if path.exists() else None))
    monkeypatch.setattr(launch, "swarm_launch_args", lambda *a, **k: [])

    def write(*records):
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return write


def _setting(name):
    return {"type": "agent-setting", "agentSetting": name, "sessionId": CONV}


def test_plain_row_with_saved_agent_gets_agent_claude_first(transcript):
    transcript({"type": "user"}, _setting("old-agent"))
    assert launch.with_swarm_args(1, ["--resume", CONV]) == ["--agent", "claude", "--resume", CONV]


def test_last_agent_setting_wins(transcript):
    transcript(_setting("a"), _setting(""), {"type": "user"})
    assert launch.with_swarm_args(1, ["--resume", CONV]) == ["--resume", CONV]


def test_swarm_row_unchanged(transcript, monkeypatch):
    monkeypatch.setattr(launch, "swarm_launch_args", lambda *a, **k: ["--agent", "loki"])
    transcript(_setting("old-agent"))
    assert launch.with_swarm_args(1, ["--resume", CONV]) == ["--agent", "loki", "--resume", CONV]


def test_no_agent_setting_unchanged(transcript):
    transcript({"type": "user", "note": "agent-setting"})
    assert launch.with_swarm_args(1, ["--resume", CONV]) == ["--resume", CONV]


def test_missing_transcript_unchanged(transcript):
    assert launch.with_swarm_args(1, ["--resume", CONV]) == ["--resume", CONV]


def test_own_agent_flag_unchanged(transcript):
    transcript(_setting("old-agent"))
    assert launch.with_swarm_args(1, ["--agent", "x", "--resume", CONV]) == ["--agent", "x", "--resume", CONV]
    assert launch.with_swarm_args(1, ["--agent=x", "--resume", CONV]) == ["--agent=x", "--resume", CONV]


def test_none_and_no_resume_stay_as_is(transcript):
    transcript(_setting("old-agent"))
    assert launch.with_swarm_args(1, None) is None
    assert launch.with_swarm_args(1, []) == []
    assert resume_agent.resume_uuid(["--model", "x"]) is None
