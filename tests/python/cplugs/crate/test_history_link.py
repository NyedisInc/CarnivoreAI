
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Tuple

import pytest

from src.cplugs.crate.forbidden import SourceForbidden
from src.cplugs.crate.write_files import write_lines

UUID = "11111111-2222-3333-4444-555555555555"
HIT = f'{{"sessionId":"{UUID}","display":"hi"}}\n'.encode()
MISS = b'{"sessionId":"other","display":"no"}\n'


class _Sink:

    def __init__(self) -> None:
        self.members: Dict[str, bytes] = {}

    def add_member(self, name: str, data: bytes) -> None:
        self.members[name] = data


def _run(path: Path) -> Tuple[_Sink, int]:
    sink = _Sink()
    item = {"source": "claude-history", "home_index": 0, "path": str(path), "match": UUID}
    total, _ = write_lines(sink, [item], SimpleNamespace(check=lambda: None))
    return sink, total


def test_a_history_link_inside_the_home_is_read_byte_exact(tmp_path: Path) -> None:
    home = tmp_path / "claude"
    home.mkdir()
    (home / "history.jsonl.nosync").write_bytes(MISS + HIT + MISS)
    os.symlink("history.jsonl.nosync", home / "history.jsonl")
    sink, total = _run(home / "history.jsonl")
    assert total == 1
    assert sink.members["lines/claude-history-0.jsonl"] == HIT


def test_a_chain_that_stays_inside_the_home_is_read(tmp_path: Path) -> None:
    home = tmp_path / "claude"
    (home / "keep").mkdir(parents=True)
    (home / "keep" / "h.real").write_bytes(HIT)
    os.symlink("keep/h.real", home / "h.mid")
    os.symlink("h.mid", home / "history.jsonl")
    assert _run(home / "history.jsonl")[1] == 1


@pytest.mark.parametrize("kind", ["outside", "directory", "chain_out"])
def test_a_link_that_is_not_a_file_in_the_home_is_refused(tmp_path: Path, kind: str) -> None:
    home = tmp_path / "claude"
    home.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "h.jsonl").write_bytes(HIT)
    (home / "adir").mkdir()
    if kind == "outside":
        os.symlink(elsewhere / "h.jsonl", home / "history.jsonl")
    elif kind == "directory":
        os.symlink("adir", home / "history.jsonl")
    else:
        os.symlink(elsewhere / "h.jsonl", home / "hop")
        os.symlink("hop", home / "history.jsonl")
    with pytest.raises(SourceForbidden):
        _run(home / "history.jsonl")


def test_a_loop_is_refused_not_a_raw_eloop(tmp_path: Path) -> None:
    home = tmp_path / "claude"
    home.mkdir()
    os.symlink("history.jsonl", home / "history.jsonl")
    with pytest.raises(SourceForbidden):
        _run(home / "history.jsonl")
