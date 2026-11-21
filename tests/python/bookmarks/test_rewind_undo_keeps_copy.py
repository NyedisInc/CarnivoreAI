
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.bookmarks import actions, rows
from src.core.bookmarks.errors import RewindRefused


def _row() -> SimpleNamespace:
    return SimpleNamespace(id=7, claude_session_uuid_source="registry")


def test_undo_keeps_copy_when_swap_back_fails(tmp_path, monkeypatch):
    copy = tmp_path / "copy.jsonl"
    copy.write_text("{}\n")
    monkeypatch.setattr(rows, "swap_conversation", lambda *a, **k: False)
    with pytest.raises(RewindRefused) as info:
        asyncio.run(actions._undo(_row(), "old-uuid", "new-uuid", copy))
    assert copy.exists()
    assert info.value.code == "undo_failed"


def test_undo_removes_copy_when_swap_back_succeeds(tmp_path, monkeypatch):
    copy = tmp_path / "copy.jsonl"
    copy.write_text("{}\n")
    monkeypatch.setattr(rows, "swap_conversation", lambda *a, **k: True)
    asyncio.run(actions._undo(_row(), "old-uuid", "new-uuid", copy))
    assert not copy.exists()
