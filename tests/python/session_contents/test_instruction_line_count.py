
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.session_contents import claude_files, codex
from src.core.session_contents import constants as C


def _refuse_whole_reads(monkeypatch: pytest.MonkeyPatch, big: Path) -> None:
    real = Path.read_text

    def guarded(self: Path, *args, **kwargs):
        if self == big:
            raise AssertionError(f"read the whole oversize file {self}")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)


def test_a_claude_instruction_over_the_read_cap_is_not_read_for_its_detail(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "MAX_READ_BYTES", 64)
    monkeypatch.setattr(C, "CLAUDE_MANAGED_DIRS", ())
    cfg, big = tmp_path / "cfg", tmp_path / "cfg" / "CLAUDE.md"
    cfg.mkdir()
    big.write_text("line\n" * 1000, encoding="utf-8")
    _refuse_whole_reads(monkeypatch, big)
    items = claude_files.instruction_items(cfg, [])
    assert [i["name"] for i in items] == ["CLAUDE.md"]
    assert "lines" not in items[0]["detail"]


def test_a_codex_instruction_detail_carries_no_line_count(tmp_path, monkeypatch):
    home = tmp_path / "codex"
    home.mkdir()
    big = home / "AGENTS.md"
    big.write_text("line\n" * 1000, encoding="utf-8")
    _refuse_whole_reads(monkeypatch, big)
    items = codex._instructions(home, [])
    assert [i["name"] for i in items] == ["AGENTS.md"] and "lines" not in items[0]["detail"]
