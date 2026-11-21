
from __future__ import annotations

import sys
from pathlib import Path

from src.core.safe_io import realpath_memo
from src.core.skill_fires import tally as tally_module
from src.core.skill_fires.store import SkillFireStore
from tests.skill_fires.test_skill_fires import _claude_lines, _write


def test_repeat_passes_resolve_the_transcript_path_once(tmp_path: Path, monkeypatch) -> None:
    realpath_memo.clear()
    calls: list[str] = []
    real = realpath_memo.os.path.realpath

    def spy(p, *a, **k):
        if sys._getframe(1).f_globals["__name__"] in (realpath_memo.__name__, tally_module.__name__):
            calls.append(p)
        return real(p, *a, **k)

    monkeypatch.setattr(realpath_memo.os.path, "realpath", spy)
    path = tmp_path / "c.jsonl"
    _write(path, _claude_lines())
    cache = tally_module.SkillTallyCache(store=SkillFireStore(tmp_path / "skill_fires.db"))
    for _ in range(5):
        assert cache.tally("claude", path).state == tally_module.STATE_MEASURED
    assert calls.count(str(path)) == 1
    realpath_memo.clear()
