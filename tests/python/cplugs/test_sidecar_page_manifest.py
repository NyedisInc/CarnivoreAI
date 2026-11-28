
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.plugins.host import sidecar_page
from src.plugins.host.plugin_manifest import from_manifest_v2, load_sidecar_manifest
from src.plugins.sdk.manifest_v2 import parse_manifest_v2

VIEWS = [{"name": "flow", "surfaces": ["panel"], "files": ["index.html"]},
         {"name": "ov", "surfaces": ["overlay"], "files": ["index.html"]}]


def _load(tmp_path: Path, ui_extra: Dict[str, Any]):
    doc = {
        "schema": 2,
        "id": "flowx",
        "name": "Flow",
        "description": "d",
        "version": "1.0.0",
        "kind": "plugin",
        "author": "me",
        "icon": "flow",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        "ui": {"views": VIEWS, **ui_extra},
    }
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "carnivore.json").write_text(json.dumps(doc), encoding="utf-8")
    return load_sidecar_manifest(tmp_path, "flowx")


def test_good_page_and_topics_reach_the_manifest(tmp_path: Path) -> None:
    m = _load(tmp_path, {"page": {"menu": "flow", "main": "flow"}, "topics": ["runs", "feed"]})
    assert dict(m.page) == {"menu": "flow", "main": "flow"} and m.page_problem == "" and m.topics == ("runs", "feed")


def test_bad_view_name_drops_only_the_page() -> None:
    v2 = parse_manifest_v2({
        "schema": 2, "id": "flowx", "name": "Flow", "description": "d", "version": "1.0.0", "kind": "plugin", "author": "me",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        "ui": {"views": VIEWS, "topics": ["runs"]},
    })
    page, problem = sidecar_page.parse_page({"menu": "flow", "main": "nope"}, v2.views)
    assert page is None and "does not ship" in problem and v2.topics == ("runs",) and v2.views


def test_view_without_panel_surface_drops_the_page(tmp_path: Path) -> None:
    m = _load(tmp_path, {"page": {"menu": "ov", "main": "flow"}})
    assert m.page is None and "panel" in m.page_problem


def test_unknown_page_key_is_ignored() -> None:
    page, problem = sidecar_page.parse_page({"menu": "flow", "main": "flow", "future": 1}, VIEWS)
    assert dict(page) == {"menu": "flow", "main": "flow"} and problem == ""


def test_bad_duplicate_and_surplus_topics_are_dropped() -> None:
    names = ["runs", "runs", "Bad Name", 5] + [f"t{i}" for i in range(9)]
    topics = sidecar_page.parse_topics(names)
    assert topics == ("runs",) + tuple(f"t{i}" for i in range(7)) and len(topics) == 8


def test_no_declaration_is_the_old_plugin(tmp_path: Path) -> None:
    m = _load(tmp_path, {})
    assert m.page is None and m.page_problem == "" and m.topics == ()
    assert from_manifest_v2(parse_manifest_v2({
        "schema": 2, "id": "flowx", "name": "Flow", "description": "d", "version": "1.0.0", "kind": "plugin", "author": "me",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
    }), "d" * 64).page is None
