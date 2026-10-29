
from __future__ import annotations

import json
from pathlib import Path

from scripts.widgets.gate import warnings_in

RECORDS = json.loads((Path(__file__).resolve().parents[3] / "src" / "data" / "widget-contracts.json").read_text(encoding="utf-8"))["widgets"]


def test_an_undeclared_widget_warns() -> None:
    assert warnings_in({"id": "core.x"}) and "remembers" in warnings_in({"id": "core.x"})[0]


def test_stateless_and_declared_widgets_do_not_warn() -> None:
    assert warnings_in({"id": "core.x", "remembers": []}) == []
    assert warnings_in({"id": "core.x", "remembers": ["status-folds"]}) == []


def test_the_task_manager_widgets_declare_what_they_remember() -> None:
    by_id = {r["id"]: r for r in RECORDS}
    for wid in ("core.task-manager", "core.task-manager-all"):
        assert "status-folds" in by_id[wid]["remembers"]
