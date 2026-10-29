
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from tests.lifecycle_helpers import ROOT, add_row, conn, row_by_uuid

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402

from src.core.session_label import InvalidLabel, set_label_for_instance

ROUTES = Path(ROOT) / "src" / "api" / "session_rename_routes.py"


def _rename_endpoint_source():
    tree = ast.parse(ROUTES.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "rename_session_endpoint":
                return ast.get_source_segment(ROUTES.read_text(), node)
    pytest.fail(
        "rename_session_endpoint not found in "
        "src/api/session_rename_routes.py"
    )


def test_the_rename_endpoint_no_longer_calls_the_tmux_rename():
    source = _rename_endpoint_source()
    assert "session_manager.rename_session(" not in source, (
        "the user-facing rename must write a label; calling the tmux "
        "rename here is what split one session into two rows"
    )
    assert "set_session_label" in source


def test_the_endpoint_no_longer_enforces_the_ascii_only_charset():
    import src.api.session_rename_routes as routes_module

    assert not hasattr(routes_module, "_RENAME_NAME_RE"), (
        "the strict tmux-name charset must not gate a label"
    )

    from src.core.session_label import validate_label

    assert validate_label("Media Compression") == "Media Compression"


def test_a_label_is_written_by_instance_triple_not_by_name_alone(conn):
    add_row(conn, uuid="u-a", name="dup", epoch=100, tmux_session_id="$0")
    add_row(conn, uuid="u-b", name="dup", epoch=200, tmux_session_id="$1")

    assert set_label_for_instance(
        conn, socket="cloude", name="dup", epoch=200, label="Second One"
    )

    assert row_by_uuid(conn, "u-b")["title"] == "Second One"
    assert row_by_uuid(conn, "u-a")["title"] is None, (
        "a write keyed on the name alone would have hit both rows"
    )


def test_writing_a_label_leaves_the_tmux_name_exactly_where_it_was(conn):
    add_row(conn, uuid="u-c", name="cloude_Media", epoch=300,
            tmux_session_id="$2")

    set_label_for_instance(
        conn, socket="cloude", name="cloude_Media", epoch=300,
        label="Media Compression",
    )

    row = row_by_uuid(conn, "u-c")
    assert row["tmux_name"] == "cloude_Media"
    assert row["tmux_created_epoch"] == 300
    assert row["title"] == "Media Compression"


def test_an_unknown_instance_reports_false_rather_than_inventing_a_row(conn):
    assert (
        set_label_for_instance(
            conn, socket="cloude", name="ghost", epoch=1, label="x"
        )
        is False
    )
    assert conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"] == 0


def test_an_invalid_label_is_refused_before_any_write(conn):
    add_row(conn, uuid="u-d", name="n", epoch=1, tmux_session_id="$3")
    with pytest.raises(InvalidLabel):
        set_label_for_instance(
            conn, socket="cloude", name="n", epoch=1, label="bad\nlabel"
        )
    assert row_by_uuid(conn, "u-d")["title"] is None
