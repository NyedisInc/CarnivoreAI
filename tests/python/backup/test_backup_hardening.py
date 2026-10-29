
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scripts.backup import phase_backup, targets
from scripts.backup.db_snapshot import diff_tables
from scripts.backup.errors import SetUnreadable
from scripts.backup.verify_set import load_manifest
from tests.python.backup.test_phase_backup import NOW, _make_state


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_a_set_and_its_copies_are_private(tmp_path: Path) -> None:
    state, dest = _make_state(tmp_path)
    final = phase_backup.take("P1", state, dest, [], now=NOW)
    assert _mode(final) == targets.PRIVATE_DIR_MODE
    for copy in (final / "db").iterdir():
        assert _mode(copy) == targets.PRIVATE_FILE_MODE
    for copy in (final / "files").rglob("*"):
        if copy.is_file():
            assert _mode(copy) == targets.PRIVATE_FILE_MODE


def test_diff_tables_keeps_the_table_name_whole() -> None:
    want = {"a:b": {"rows": 1, "sha256": "x"}}
    got = {"a:b": {"rows": 2, "sha256": "y"}}
    (diff,) = diff_tables(want, got)
    assert diff.table == "a:b"
    assert "1 rows -> 2 rows" in diff.message


@pytest.mark.parametrize("section,key", [("databases", "copy"), ("databases", "tables"), ("databases", "file_sha256"),
                                         ("files", "sha256"), ("files", "base"), ("trees", "files")])
def test_a_manifest_missing_an_entry_key_is_unreadable_not_a_crash(tmp_path: Path, section: str, key: str) -> None:
    state, dest = _make_state(tmp_path)
    final = phase_backup.take("P1", state, dest, [], now=NOW)
    path = final / targets.MANIFEST_NAME
    manifest = json.loads(path.read_text())
    entry = next(iter(manifest[section].values()))
    del entry[key]
    path.write_text(json.dumps(manifest))
    with pytest.raises(SetUnreadable):
        load_manifest(final)
    assert phase_backup.main(["--state-dir", str(state), "--dest", str(dest), "verify", final.name]) == 2
