
from __future__ import annotations

import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_models import (  # noqa: E402
    SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    SESSION_ATTRIBUTION_NONE,
    SESSION_ATTRIBUTION_UNKNOWN,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.project_attribution import (  # noqa: E402
    attribute,
    attribution_is_determined,
    normalize_path_for_match,
    normalize_roots,
    unresolved_roots,
)
from src.core.session_identity import record_instance  # noqa: E402
from src.core.session_store import needs_attention  # noqa: E402
from tests.s7_helpers import TEST_SOCKET, migrated_connection  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    with closing(migrated_connection(tmp_path)):
        pass
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection




def test_an_exact_match_attributes_to_that_project():
    assert attribute("/Users/example/Development/app",
                     {"/Users/example/Development/app": 7}) == (
        7, SESSION_ATTRIBUTION_DERIVED_DEEPEST)


def test_a_subdirectory_attributes_to_the_project_above_it():
    assert attribute("/Users/example/Development/app/src/api",
                     {"/Users/example/Development/app": 7}) == (
        7, SESSION_ATTRIBUTION_DERIVED_DEEPEST)


def test_the_deepest_containing_root_wins_not_the_first_or_the_shortest():
    roots = {
        "/Users/example/Development": 8,
        "/Users/example/Development/app": 7,
        "/Users/example": 5,
    }
    assert attribute("/Users/example/Development/app/src", roots) == (
        7, SESSION_ATTRIBUTION_DERIVED_DEEPEST)


def test_deepest_is_measured_in_components_not_string_length():
    roots = {
        "/averyveryverylongtopleveldirectoryname": 1,
        "/a/b/c": 2,
    }
    assert attribute("/a/b/c/d", roots) == (
        2, SESSION_ATTRIBUTION_DERIVED_DEEPEST)


def test_a_sibling_sharing_a_name_prefix_does_not_match():
    assert attribute("/a/bc/session", {"/a/b": 3}) == (
        None, SESSION_ATTRIBUTION_NONE)


def test_a_tilde_working_dir_matches_an_expanded_root():
    home = str(Path.home())
    assert attribute("~/s7project/sub", {f"{home}/s7project": 4}) == (
        4, SESSION_ATTRIBUTION_DERIVED_DEEPEST)


def test_a_tilde_root_matches_an_absolute_working_dir():
    home = str(Path.home())
    assert attribute(f"{home}/s7project/sub", {"~/s7project": 4}) == (
        4, SESSION_ATTRIBUTION_DERIVED_DEEPEST)


def test_a_symlinked_path_is_matched_as_written_and_never_resolved(tmp_path):
    real = tmp_path / "real-project"
    (real / "src").mkdir(parents=True)
    link = tmp_path / "linked-project"
    link.symlink_to(real, target_is_directory=True)

    declared_root = str(link)
    working_dir = str(link / "src")

    project_id, attribution = attribute(working_dir, {declared_root: 11})
    assert (project_id, attribution) == (
        11, SESSION_ATTRIBUTION_DERIVED_DEEPEST)
    assert normalize_path_for_match(working_dir) == working_dir
    assert "real-project" not in normalize_path_for_match(working_dir)


def test_a_symlinked_session_does_not_match_the_targets_project(tmp_path):
    real = tmp_path / "real-project"
    (real / "src").mkdir(parents=True)
    link = tmp_path / "linked-project"
    link.symlink_to(real, target_is_directory=True)

    project_id, attribution = attribute(str(link / "src"), {str(real): 11})
    assert (project_id, attribution) == (None, SESSION_ATTRIBUTION_NONE)


def test_no_call_in_the_attribution_path_resolves_a_path():
    import ast

    for module in ("project_attribution", "session_attribution",
                   "session_adopt_persist", "tmux_session_cwd"):
        source = (ROOT / "src" / "core" / f"{module}.py").read_text()
        tree = ast.parse(source)
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("resolve", "realpath")
        ]
        assert offenders == [], (
            f"{module}.py calls resolve()/realpath() at lines {offenders}. "
            "That collapses symlinks and rewrites the path the user chose"
        )




def test_a_directory_in_no_project_is_NONE_and_that_is_a_real_answer():
    project_id, attribution = attribute("/somewhere/else", {"/a/b": 1})
    assert project_id is None
    assert attribution == SESSION_ATTRIBUTION_NONE
    assert attribution_is_determined(attribution) is True


def test_an_unreadable_working_dir_is_UNKNOWN_and_never_none():
    for unreadable in (None, "", "   "):
        project_id, attribution = attribute(unreadable, {"/a/b": 1})
        assert project_id is None
        assert attribution == SESSION_ATTRIBUTION_UNKNOWN
        assert attribution_is_determined(attribution) is False


def test_a_path_that_cannot_be_situated_is_UNKNOWN_not_none():
    for unsituatable in ("relative/path", "/a/../b", "../up"):
        _, attribution = attribute(unsituatable, {"/a": 1, "/b": 2})
        assert attribution == SESSION_ATTRIBUTION_UNKNOWN, unsituatable


def test_none_and_unknown_are_different_values_at_the_store_layer(conn):
    record_instance(
        conn, socket=TEST_SOCKET, name="knows", epoch=1,
        origin=SESSION_ORIGIN_OBSERVED,
        project_attribution=SESSION_ATTRIBUTION_NONE,
    )
    record_instance(
        conn, socket=TEST_SOCKET, name="cannot-tell", epoch=2,
        origin=SESSION_ORIGIN_OBSERVED,
        project_attribution=SESSION_ATTRIBUTION_UNKNOWN,
    )
    flagged = {row["tmux_name"] for row in needs_attention(conn)}
    assert "cannot-tell" in flagged
    assert "knows" not in flagged, (
        "'belongs to no project' is a complete answer and must not be "
        "surfaced as something the user has to look at"
    )


def test_a_root_that_cannot_be_situated_is_dropped_and_named():
    roots = {"/good": 1, "relative-root": 2}
    assert normalize_roots(roots) == {"/good": 1}
    assert unresolved_roots(roots.keys()) == ("relative-root",)


def test_duplicate_roots_resolve_to_the_lowest_project_id():
    home = str(Path.home())
    assert normalize_roots({f"{home}/dup": 9, "~/dup": 3}) == {
        f"{home}/dup": 3}
