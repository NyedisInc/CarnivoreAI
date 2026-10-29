
from __future__ import annotations

from contextlib import closing

import pytest

from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.project_colors.calm_remap import nearest_calm_color
from src.core.project_colors.legacy_keys import LEGACY_KEY_HEX, LEGACY_KEY_REFERENCE_HEX, LEGACY_KEYS, stored_hex
from src.core.project_colors.palette import SOFT_PALETTE
from src.core.project_writes import ProjectColorInvalid, create_project, update_project

INSERT = (
    "INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at, color) "
    "VALUES (?, ?, ?, 'user', 'x', 'x', ?)"
)
EXPECTED = {
    "orange": "#a7593d", "green": "#817040", "cyan": "#7b75e2", "yellow": "#c07e45",
    "coral": "#c07e45", "violet": "#a167cf", "green-bright": "#817040", "yellow-bright": "#c07e45",
}


def test_every_stored_legacy_key_becomes_its_fixed_hex_and_a_second_run_changes_nothing(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        with conn:
            run_chain(conn, 0, 97)
            for i, key in enumerate(LEGACY_KEYS):
                conn.execute(INSERT, (f"/k{i}", f"/k{i}", f"k{i}", key))
            conn.execute(INSERT, ("/h", "/h", "h", "#966356"))
            conn.execute(INSERT, ("/n", "/n", "n", None))
        with conn:
            run_chain(conn, 97, CURRENT_SCHEMA_VERSION)
        got = [r[0] for r in conn.execute("SELECT color FROM projects ORDER BY id")]
        assert got == [EXPECTED[k] for k in LEGACY_KEYS] + ["#966356", None]
        with conn:
            run_chain(conn, 97, CURRENT_SCHEMA_VERSION)
        assert [r[0] for r in conn.execute("SELECT color FROM projects ORDER BY id")] == got


def test_a_key_write_is_refused_and_the_stored_color_is_untouched(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, CURRENT_SCHEMA_VERSION)
        (tmp_path / "a").mkdir()
        pid = create_project(conn, name="a", path=str(tmp_path / "a"))["id"]
        update_project(conn, pid, color="#aabbcc")
        for key in LEGACY_KEYS:
            with pytest.raises(ProjectColorInvalid, match="no longer accepted"):
                update_project(conn, pid, color=key)
        assert update_project(conn, pid)["color"] == "#aabbcc"


def test_the_conversion_table_is_complete_and_import_doors_convert_or_drop():
    assert LEGACY_KEY_HEX == EXPECTED and set(LEGACY_KEY_HEX) == set(LEGACY_KEYS)
    assert stored_hex("Cyan") is None and stored_hex("#ABCDEF") == "#abcdef"
    assert stored_hex("violet") == "#a167cf" and stored_hex(None) is None
    assert LEGACY_KEY_REFERENCE_HEX["cyan"] == "#6cb0e0" and LEGACY_KEY_REFERENCE_HEX["orange"] == "#ff4652"
    assert all(v in SOFT_PALETTE and v == nearest_calm_color(k) for k, v in LEGACY_KEY_HEX.items())
