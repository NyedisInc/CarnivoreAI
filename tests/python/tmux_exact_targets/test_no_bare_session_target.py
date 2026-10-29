
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src"
BARE_TARGET = re.compile(r'["\']-t["\']\s*,\s*[\w.]*tmux_session\s*[,)]')


def _offenders() -> list[str]:
    hits: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in BARE_TARGET.finditer(text):
            hits.append(f"{path.relative_to(SRC.parent)}:{text.count(chr(10), 0, match.start()) + 1}")
    return hits


def test_no_dash_t_takes_a_bare_session_name() -> None:
    assert _offenders() == []


def test_the_scan_goes_red_on_a_planted_offender(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "src"
    root.mkdir()
    (root / "bad.py").write_text('run("send-keys", "-t",\n    self.tmux_session, "x")\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "SRC", root)
    assert _offenders() == ["src/bad.py:1"]
