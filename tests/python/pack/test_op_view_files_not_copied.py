from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Tuple

from src.core.pack.migrate import ddl, ops


def _child_view(summary: object) -> Dict[str, Any]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ddl.apply_pack_migrate(conn)
    common = dict(kind="project", role="source", source_install_id="a", target_install_id="b")
    ops.create(conn, op_id="parent", subject_uid="co", **{**common, "kind": "company"})
    ops.create(conn, op_id="child", subject_uid="p", parent_id="parent", detail={"name": "trader", "summary": summary}, **common)
    return ops.view(conn, "parent")["children"][0]


def _listed(summary: object) -> Tuple[List[str], int]:
    child = _child_view(summary)
    return child["task_files_not_copied"], child["task_files_not_copied_more"]


def test_child_lists_the_files_its_receiver_could_not_copy() -> None:
    assert _listed({"task_files_not_copied": ["shot.png"]}) == (["shot.png"], 0)


def test_child_without_a_summary_lists_nothing() -> None:
    assert _listed(None) == ([], 0)


def test_same_named_files_all_stay() -> None:
    assert _listed({"task_files_not_copied": ["image.png"] * 7}) == (["image.png"] * 7, 0)


def test_a_long_list_is_capped_and_the_rest_counted() -> None:
    names, more = _listed({"task_files_not_copied": [f"f{i}.png" for i in range(25)]})
    assert (len(names), more, names[0]) == (20, 5, "f0.png")


def test_a_malformed_summary_lists_nothing() -> None:
    for bad in ("abc", {"task_files_not_copied": "abc"}, {"task_files_not_copied": None}, {"task_files_not_copied": 5}, 7):
        assert _listed(bad) == ([], 0)
