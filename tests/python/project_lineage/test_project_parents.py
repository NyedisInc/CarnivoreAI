
from __future__ import annotations

from src.core.project_lineage.parents import parent_project_ids


def _p(pid, root, **extra):
    return {"id": pid, "root": root, **extra}


def test_nearest_ancestor_wins_and_component_boundaries_hold():
    rows = [_p(1, "/org"), _p(2, "/org/imc"), _p(3, "/org/imc/amerifund"), _p(4, "/org/imc/amerifund/support"),
            _p(5, "/org/imcx"), _p(6, "/org/imc/amerifund/projects/AMF-001")]
    assert parent_project_ids(rows) == {1: None, 2: 1, 3: 2, 4: 3, 5: 1, 6: 3}


def test_string_prefix_is_not_a_parent():
    assert parent_project_ids([_p(1, "/a/b"), _p(2, "/a/bc")]) == {1: None, 2: None}


def test_trailing_slash_and_dot_parts_are_normalized():
    assert parent_project_ids([_p(1, "/a/b/"), _p(2, "/a/b/./c")]) == {1: None, 2: 1}


def test_archived_projects_are_never_parents_but_still_get_one():
    rows = [_p(1, "/a"), _p(2, "/a/b", archived_at="2026-10-01"), _p(3, "/a/b/c")]
    assert parent_project_ids(rows) == {1: None, 2: 1, 3: 1}


def test_same_host_only():
    rows = [_p(1, "/a", host_key="local"), _p(2, "/a/b", host_key="peer-x"), _p(3, "/a/c")]
    assert parent_project_ids(rows) == {1: None, 2: None, 3: 1}


def test_no_lineage_is_all_none_and_bad_rows_are_skipped():
    rows = [_p(1, "/x"), _p(2, "/y"), _p(None, "/x/z"), _p(3, None), _p(4, "relative/path"), _p(True, "/x/t")]
    assert parent_project_ids(rows) == {1: None, 2: None, 3: None, 4: None}


def test_duplicate_roots_resolve_to_the_lower_id_and_never_to_self():
    rows = [_p(9, "/a"), _p(2, "/a"), _p(5, "/a/b")]
    assert parent_project_ids(rows) == {9: None, 2: None, 5: 2}


def test_one_pass_scales_linearly():
    rows = [_p(i, f"/root/{i}") for i in range(1, 20001)] + [_p(0, "/root")]
    out = parent_project_ids(rows)
    assert out[0] is None and all(out[i] == 0 for i in range(1, 20001))
