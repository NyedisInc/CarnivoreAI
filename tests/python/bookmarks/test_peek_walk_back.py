
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from src.core.bookmarks import compactions, locate, predecessor, preview

SESSION = "11111111-2222-4333-8444-555555555555"


def _rec(uuid: str, parent: Optional[str], kind: str, text: str = "", **extra) -> dict:
    base = {"parentUuid": parent, "isSidechain": False, "uuid": uuid, "sessionId": SESSION,
            "timestamp": "2026-10-10T00:00:00.000Z", "type": kind}
    if kind == "user":
        base["message"] = {"role": "user", "content": text}
    elif kind == "assistant":
        base["message"] = {"role": "assistant", "id": f"msg_{uuid}", "content": [{"type": "text", "text": text}]}
    base.update(extra)
    return base


def _boundary(uuid: str, logical_parent: str) -> dict:
    return _rec(uuid, None, "system", subtype="compact_boundary", content="Conversation compacted",
                logicalParentUuid=logical_parent)


def _write(path: Path, records: List[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in records) + "\n")
    return path


def _texts(path: Path, uuid: str, turns: int = 4) -> List[str]:
    return [p["text"] for p in preview.preview_parts(path, uuid, turns)]


def test_a_boundary_whose_logical_parent_is_gone_walks_back_in_file_order(tmp_path):
    path = _write(tmp_path / "a.jsonl", [
        _rec("u1", None, "user", "fix the bug"), _rec("a1", "u1", "assistant", "fixed it"),
        _boundary("cb", "trimmed-away"), _rec("s1", "cb", "user", "summary of the chat")])
    assert _texts(path, "cb") == ["fix the bug", "fixed it"]


def test_a_boundary_whose_chain_loops_back_onto_itself_still_shows_the_chat_before_it(tmp_path):
    path = _write(tmp_path / "b.jsonl", [
        _rec("u1", None, "user", "first ask"), _rec("a1", "u1", "assistant", "first answer"),
        _boundary("cb", "att2"), _rec("att1", "cb", "attachment"), _rec("att2", "att1", "attachment"),
        _rec("s1", "att2", "user", "summary")])
    assert _texts(path, "cb") == ["first ask", "first answer"]


def test_a_boundary_at_the_top_of_a_resumed_file_follows_into_the_file_it_came_from(tmp_path, monkeypatch):
    older = _write(tmp_path / "old.jsonl", [_rec("u1", None, "user", "original ask"),
                                            _rec("a1", "u1", "assistant", "original answer")])
    newer = _write(tmp_path / "new.jsonl", [_boundary("cb", "a1"), _rec("s1", "cb", "user", "summary")])
    found = predecessor.find_holder(newer, "a1", roots=[tmp_path])
    assert found == older
    monkeypatch.setattr(locate, "_roots", lambda: (tmp_path,))
    assert _texts(newer, "cb") == ["original ask", "original answer"]


def test_a_boundary_with_nothing_before_it_anywhere_gives_no_parts(tmp_path, monkeypatch):
    path = _write(tmp_path / "c.jsonl", [_boundary("cb", "nowhere"), _rec("s1", "cb", "user", "summary")])
    monkeypatch.setattr(locate, "_roots", lambda: (tmp_path,))
    assert preview.preview_parts(path, "cb", 4) == []


def test_a_milestone_with_only_a_line_number_resolves_to_the_boundary_on_that_line(tmp_path):
    path = _write(tmp_path / "d.jsonl", [_rec("u1", None, "user", "x"), _boundary("cb", "u1")])
    assert compactions._boundary_by_line(path, 2) == "cb"
    assert compactions._boundary_by_line(path, 1) is None
    assert compactions._boundary_by_line(path, 99) is None
    assert compactions._boundary_by_line(path, None) is None
