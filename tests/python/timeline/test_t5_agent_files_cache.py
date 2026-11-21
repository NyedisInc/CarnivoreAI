
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from src.core.timeline import files as tfiles

N_FILES = 50


@pytest.fixture()
def conv(tmp_path: Path):
    tfiles._LISTING_CACHE.clear()
    main = tmp_path / "c.jsonl"
    main.write_text("")
    folder = tmp_path / "c" / "subagents"
    folder.mkdir(parents=True)
    for i in range(N_FILES):
        (folder / f"agent-a{i:03d}.jsonl").write_text("{}\n")
    return os.path.realpath(main), folder


def _bump(folder: Path, seconds: int = 5) -> None:
    t = time.time() + seconds
    os.utime(folder, (t, t))


def test_unchanged_folder_skips_listing_and_resolves_one_realpath(conv, monkeypatch) -> None:
    main, _ = conv
    first = tfiles.agent_files(main)
    assert len(first) == N_FILES
    calls = {"listdir": 0, "scandir": 0, "realpath": 0}
    real = {"listdir": os.listdir, "scandir": os.scandir}
    real_realpath = os.path.realpath

    def counted_listdir(*a, **k):
        calls["listdir"] += 1
        return real["listdir"](*a, **k)

    def counted_scandir(*a, **k):
        calls["scandir"] += 1
        return real["scandir"](*a, **k)

    def counted_realpath(*a, **k):
        calls["realpath"] += 1
        return real_realpath(*a, **k)

    monkeypatch.setattr(os, "listdir", counted_listdir)
    monkeypatch.setattr(os, "scandir", counted_scandir)
    monkeypatch.setattr(os.path, "realpath", counted_realpath)
    assert tfiles.agent_files(main) == first
    assert calls["listdir"] == 0 and calls["scandir"] == 0
    assert calls["realpath"] <= 1


def test_added_and_removed_files_show_on_next_call(conv) -> None:
    main, folder = conv
    tfiles.agent_files(main)
    (folder / "agent-new.jsonl").write_text("{}\n")
    _bump(folder)
    assert "new" in tfiles.agent_files(main)
    (folder / "agent-new.jsonl").unlink()
    (folder / "agent-a000.jsonl").unlink()
    _bump(folder, 10)
    got = tfiles.agent_files(main)
    assert "new" not in got and "a000" not in got and len(got) == N_FILES - 1


def test_symlinked_agent_file_resolves_to_real_target(conv, tmp_path) -> None:
    main, folder = conv
    target = tmp_path / "elsewhere.jsonl"
    target.write_text("{}\n")
    (folder / "agent-linked.jsonl").symlink_to(target)
    _bump(folder)
    got = tfiles.agent_files(main)
    assert got["linked"] == os.path.realpath(target)
    assert got["a001"] == os.path.join(os.path.realpath(folder), "agent-a001.jsonl")


def test_cache_is_bounded(conv, monkeypatch) -> None:
    main, _ = conv
    monkeypatch.setattr(tfiles, "LISTING_CACHE_FOLDERS", 2)
    for i in range(4):
        d = Path(main).parent / f"x{i}.jsonl"
        d.write_text("")
        (Path(main).parent / f"x{i}" / "subagents").mkdir(parents=True)
        tfiles.agent_files(str(d))
    assert len(tfiles._LISTING_CACHE) <= 2
