
import json
import sqlite3
from pathlib import Path

import pytest

from src.cplugs.host.legacy_move import MARKER, move_legacy_state


def _addon_era(state: Path) -> None:
    old = state / "addons"
    (old / "huddle").mkdir(parents=True)
    (old / "state.json").write_text(json.dumps({"version": 1, "addons": {"huddle": {"enabled": True, "revision": 3}}}))
    conn = sqlite3.connect(str(old / "huddle" / "huddle.db"))
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (7)")
    conn.commit()
    conn.close()
    (old / "huddle" / "note.txt").write_bytes(b"bytes\x00kept")


def test_fresh_install_is_a_noop(tmp_path):
    assert move_legacy_state(tmp_path) == "none"
    assert not (tmp_path / "cplugs").exists()


def test_pre_addon_install_leaves_huddle_db_for_the_storage_move(tmp_path):
    (tmp_path / "huddle.db").write_bytes(b"x")
    assert move_legacy_state(tmp_path) == "none"
    assert not (tmp_path / "cplugs").exists() and (tmp_path / "huddle.db").exists()


def test_addon_era_install_moves_everything_and_keeps_the_old_folder(tmp_path):
    _addon_era(tmp_path)
    assert move_legacy_state(tmp_path) == "moved"
    new = tmp_path / "cplugs"
    state = json.loads((new / "state.json").read_text())
    assert state["cplugs"]["huddle"]["revision"] == 3 and "addons" not in state
    conn = sqlite3.connect(str(new / "huddle" / "huddle.db"))
    assert conn.execute("SELECT x FROM t").fetchall() == [(7,)]
    conn.close()
    assert (new / "huddle" / "note.txt").read_bytes() == b"bytes\x00kept"
    assert (tmp_path / "addons" / "state.json").exists() and (tmp_path / "addons" / MARKER).exists()
    assert not (tmp_path / ".cplugs.moving").exists()


def test_second_start_is_a_noop(tmp_path):
    _addon_era(tmp_path)
    move_legacy_state(tmp_path)
    (tmp_path / "cplugs" / "state.json").write_text("{\"version\": 1, \"cplugs\": {}}")
    assert move_legacy_state(tmp_path) == "done"
    assert json.loads((tmp_path / "cplugs" / "state.json").read_text())["cplugs"] == {}


def test_both_present_without_marker_cplugs_wins(tmp_path):
    _addon_era(tmp_path)
    (tmp_path / "cplugs").mkdir()
    (tmp_path / "cplugs" / "state.json").write_text("{\"version\": 1, \"cplugs\": {}}")
    assert move_legacy_state(tmp_path) == "ignored"
    assert json.loads((tmp_path / "cplugs" / "state.json").read_text())["cplugs"] == {}
    assert not (tmp_path / "addons" / MARKER).exists()


def test_failed_copy_publishes_nothing(tmp_path, monkeypatch):
    _addon_era(tmp_path)
    import src.cplugs.host.legacy_move as lm

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(lm, "_copy_db", boom)
    with pytest.raises(OSError):
        move_legacy_state(tmp_path)
    assert not (tmp_path / "cplugs").exists() and not (tmp_path / ".cplugs.moving").exists()
    assert (tmp_path / "addons" / "state.json").exists()
