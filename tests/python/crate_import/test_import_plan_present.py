
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from src.core.crate_import import keymap
from src.core.crate_import.model import ImportRequest
from src.core.crate_import.plan import build_plan
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_import.test_import_work_side import imported

NO_NATURAL_KEY = ("cloude.db.lineage_edges", "cloude.db.work_card_rules", "cloude.db.work_project_roles", "stats.db.stats_annotations")


def replan(tmp_path: Path, shift: int = 0) -> Any:
    crate, install, receipt = imported(tmp_path, shift=shift)
    with cf.open_crate(crate.path) as reader:
        return receipt, build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)


def test_rows_already_here_are_present_in_the_plan(tmp_path: Path) -> None:
    receipt, plan = replan(tmp_path)
    for key in NO_NATURAL_KEY:
        assert receipt.rows[key]["inserted"] >= 1, key
        assert plan["rows"][key]["insert"] == 0 and plan["rows"][key]["present"] >= 1, (key, plan["rows"][key])


def test_rows_present_under_a_remapped_key_are_present_in_the_plan(tmp_path: Path) -> None:
    receipt, plan = replan(tmp_path, shift=1)
    for key in NO_NATURAL_KEY:
        assert receipt.rows[key]["inserted"] >= 1, key
        assert plan["rows"][key]["insert"] == 0 and plan["rows"][key]["present"] >= 1, (key, plan["rows"][key])


def test_the_check_goes_red_when_nothing_is_looked_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keymap.LocalTables, "has_identical", lambda self, *args: False)
    _receipt, plan = replan(tmp_path)
    assert plan["rows"]["cloude.db.lineage_edges"]["insert"] >= 1


def test_a_row_with_an_id_pointer_cannot_be_judged(tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / "main.db")) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE layout_members (layout_id INTEGER, session_row_id INTEGER, position INTEGER)")
        conn.execute("INSERT INTO layout_members VALUES (1, 2, 0)")
        local = keymap.LocalTables(None, conn)  # type: ignore[arg-type]
        same = {"layout_id": 1, "session_row_id": 2, "position": 0}
        assert keymap.identity_values("cloude.db", "layout_members", same) is None
        assert keymap.classify_row(local, "cloude.db", "layout_members", same, {}) == keymap.INSERT
        conn.execute("CREATE TABLE lineage_edges (parent_id TEXT, child_id TEXT, edge_kind TEXT)")
        conn.execute("INSERT INTO lineage_edges VALUES ('a', 'b', 'fork')")
        edge = {"parent_id": "a", "child_id": "b", "edge_kind": "fork"}
        assert keymap.classify_row(local, "cloude.db", "lineage_edges", edge, {}) == keymap.PRESENT
        assert keymap.classify_row(local, "cloude.db", "lineage_edges", {**edge, "edge_kind": "spawn"}, {}) == keymap.INSERT


def test_a_zstd_crate_without_zstd_is_a_blocked_plan_not_an_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.blobcodec import codec
    from tests.python.crate_import.test_import_plan import export_crate, plan_of, target

    crate = export_crate(tmp_path)
    install = target(tmp_path, crate)
    if codec._zstd is None:
        pytest.skip("this interpreter writes lzma crates, so there is no zstd blob to fail on")
    monkeypatch.setattr(codec, "_zstd", None)
    plan = plan_of(crate, install.env)
    assert plan["ok"] is False and plan["fingerprint"] == ""
    assert [b["code"] for b in plan["blockers"]] == ["codec_unavailable"]
