
from pathlib import Path

import pytest

from src.core.bookmarks import transcript_index
from src.core.bookmarks.errors import TranscriptUnavailable


def _sparse(path: Path, size: int) -> Path:
    with path.open("wb") as stream:
        stream.truncate(size)
    return path


def test_cap_is_two_gigabytes() -> None:
    assert transcript_index.MAX_TRANSCRIPT_BYTES == 2 * 1024 ** 3
    assert transcript_index.MAX_TRANSCRIPT_LABEL == "2 GB"


def test_over_the_old_512_mb_is_still_indexed(tmp_path: Path) -> None:
    path = _sparse(tmp_path / "big.jsonl", 600 * 1024 ** 2)
    index = transcript_index.build_index(path)
    assert index.size == 600 * 1024 ** 2


def test_over_the_cap_is_refused(tmp_path: Path) -> None:
    path = _sparse(tmp_path / "huge.jsonl", 2 * 1024 ** 3 + 1)
    with pytest.raises(TranscriptUnavailable, match="over the 2 GB bookmark limit"):
        transcript_index.build_index(path)
