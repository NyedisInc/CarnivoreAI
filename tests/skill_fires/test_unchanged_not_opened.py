
from __future__ import annotations

import builtins
import os
from pathlib import Path

from src.core.skill_fires.scan import scan_file
from src.core.skill_fires.store import SkillFireStore
from tests.skill_fires.test_skill_fires import _claude_lines, _write


def test_unchanged_file_is_not_opened_and_appended_file_is_read(tmp_path: Path, monkeypatch) -> None:
    store = SkillFireStore(tmp_path / "skill_fires.db")
    path = tmp_path / "c.jsonl"
    _write(path, _claude_lines())
    target = os.path.realpath(path)
    scan_file(store, str(path), "claude", "default")
    first = store.count(target)
    opened: list[str] = []
    real_open = builtins.open

    def spying(file, *args, **kwargs):
        if str(file) == target:
            opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spying)
    for _ in range(5):
        assert scan_file(store, str(path), "claude", "default").state == "ok"
    assert opened == []
    _write(path, _claude_lines() * 2)
    scan_file(store, str(path), "claude", "default")
    assert len(opened) == 1 and store.count(target) == first * 2
