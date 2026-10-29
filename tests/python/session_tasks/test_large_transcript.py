
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
from structlog.testing import capture_logs

from src.core.session_tasks import reader as reader_mod
from src.core.session_tasks import service
from src.core.session_tasks.reader import TaskReader, TranscriptUnreadable

OLD_CAP = 256 * 1024 * 1024


def _todo_line(subject: str) -> str:
    rec = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "TodoWrite",
                                                          "input": {"todos": [{"content": subject, "activeForm": subject, "status": "pending"}]}}]}}
    return json.dumps(rec) + "\n"


def test_a_transcript_past_the_old_cap_folds(tmp_path: Path) -> None:
    path = tmp_path / "big.jsonl"
    with path.open("wb") as handle:
        handle.write(_todo_line("keep going").encode())
        handle.truncate(OLD_CAP + 1)
    reader = TaskReader()
    items = reader.read(path)
    assert [i.subject for i in items] == ["keep going"]
    assert reader.read(path) is items


def _info() -> Any:
    return SimpleNamespace(session=SimpleNamespace(id="ses_1", working_dir="/x"), label="L", tmux_session="t",
                           claude_session_uuid="u", agent_family="claude")


def test_a_truly_unreadable_file_warns_once_per_identity_and_size_bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "big.jsonl"
    path.write_bytes(b"x" * 100)
    monkeypatch.setattr(reader_mod, "MAX_BYTES", 10)
    where = SimpleNamespace(outcome=service.CONVERSATION_PRESENT, path=path)
    monkeypatch.setattr(service, "locate_transcript", lambda *a, **k: where)
    reader = TaskReader()

    def pass_() -> str:
        return asyncio.run(service.tasks_for(_info(), reader)).state

    with capture_logs() as logs:
        states = [pass_() for _ in range(5)]
        assert states == ["unknown"] * 5
        warned = [e for e in logs if e["event"] == "session_tasks_unreadable"]
        assert len(warned) == 1
        path.write_bytes(b"x" * 1000)
        pass_()
        pass_()
        assert len([e for e in logs if e["event"] == "session_tasks_unreadable"]) == 2


def test_the_refusal_is_flagged_repeat_and_a_readable_file_clears_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(_todo_line("a"))
    reader = TaskReader()
    monkeypatch.setattr(reader_mod, "MAX_BYTES", 5)
    flags: List[bool] = []
    for _ in range(2):
        with pytest.raises(TranscriptUnreadable) as caught:
            reader.read(path)
        flags.append(caught.value.repeat)
    assert flags == [False, True]
    monkeypatch.setattr(reader_mod, "MAX_BYTES", 1 << 20)
    assert [i.subject for i in reader.read(path)] == ["a"]
