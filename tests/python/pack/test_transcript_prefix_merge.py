
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from src.core.pack.migrate import transcripts

ROOT = "/Users/example/carnivore-projects/ledgerbot"
OLD = b'{"n":1}\n{"n":2}\n'
NEW = OLD + b'{"n":3}\n'


def _archive(tmp_path: Path, content: bytes) -> str:
    path = tmp_path / "in.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("c.jsonl")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return str(path)


def _local(tmp_path: Path, content: bytes) -> Path:
    folder = transcripts.target_folder(ROOT, tmp_path / "projects")
    folder.mkdir(parents=True)
    (folder / "c.jsonl").write_bytes(content)
    return folder


def test_a_local_prefix_is_replaced_and_the_undo_restores_the_original_bytes(tmp_path: Path) -> None:
    folder = _local(tmp_path, OLD)
    written, same, replaced = transcripts.unpack(_archive(tmp_path, NEW), ROOT, tmp_path / "projects")
    assert (written, same, replaced) == ([], [], ["c.jsonl"])
    assert (folder / "c.jsonl").read_bytes() == NEW
    transcripts.restore_replaced(folder, replaced)
    assert (folder / "c.jsonl").read_bytes() == OLD
    transcripts.restore_replaced(folder, replaced)
    assert (folder / "c.jsonl").read_bytes() == OLD


def test_drop_backups_keeps_the_longer_copy(tmp_path: Path) -> None:
    folder = _local(tmp_path, OLD)
    _w, _s, replaced = transcripts.unpack(_archive(tmp_path, NEW), ROOT, tmp_path / "projects")
    transcripts.drop_backups(folder, replaced)
    assert sorted(p.name for p in folder.iterdir()) == ["c.jsonl"] and (folder / "c.jsonl").read_bytes() == NEW


def test_equal_bytes_are_a_no_op(tmp_path: Path) -> None:
    folder = _local(tmp_path, OLD)
    assert transcripts.unpack(_archive(tmp_path, OLD), ROOT, tmp_path / "projects") == ([], ["c.jsonl"], [])
    assert [p.name for p in folder.iterdir()] == ["c.jsonl"]


@pytest.mark.parametrize("local", [b'{"n":1}\n{"n":X}\n', NEW + b"more\n", b'{"n":9}\n{"n":2}\n{"n":3}\n'], ids=["diverged", "local_longer", "same_length_other_bytes"])
def test_anything_else_is_a_clash_and_the_local_file_is_untouched(tmp_path: Path, local: bytes) -> None:
    folder = _local(tmp_path, local)
    with pytest.raises(transcripts.TranscriptError) as caught:
        transcripts.unpack(_archive(tmp_path, NEW), ROOT, tmp_path / "projects")
    assert caught.value.code == "transcript_clash"
    assert (folder / "c.jsonl").read_bytes() == local and [p.name for p in folder.iterdir()] == ["c.jsonl"]
