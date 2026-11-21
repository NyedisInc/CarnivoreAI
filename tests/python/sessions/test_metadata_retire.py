
from __future__ import annotations

from src.core.sessions.metadata_retire import RETIRED_SUFFIX, retire_metadata_file


def test_retire_moves_file_aside_keeping_content(tmp_path):
    meta = tmp_path / "session_metadata.json"
    meta.write_text('{"sessions": []}')
    retired = retire_metadata_file(meta)
    assert not meta.exists()
    assert retired == tmp_path / ("session_metadata.json" + RETIRED_SUFFIX)
    assert retired.read_text() == '{"sessions": []}'


def test_retire_missing_file_is_a_noop(tmp_path):
    assert retire_metadata_file(tmp_path / "session_metadata.json") is None


def test_retire_replaces_previous_retired_copy(tmp_path):
    meta = tmp_path / "session_metadata.json"
    meta.write_text("one")
    retire_metadata_file(meta)
    meta.write_text("two")
    retired = retire_metadata_file(meta)
    assert retired.read_text() == "two"
