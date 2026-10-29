
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.cplugs.host.sidecar_manifest import load_sidecar_manifest, with_sidecar_facts

VIEWS = [{"name": "flow", "surfaces": ["panel"], "files": ["index.html"]},
         {"name": "ov", "surfaces": ["overlay"], "files": ["index.html"]}]


def _load(tmp_path: Path, side: Dict[str, Any]):
    (tmp_path / "cplug.json").write_text(json.dumps({"schema": 1, "id": "flowx", "name": "Flow", "description": "d", "version": "1.0.0",
                                                     "entry": "main.py", "views": VIEWS}))
    (tmp_path / "main.py").write_text("")
    (tmp_path / "carnivore.json").write_text(json.dumps({"icon": "flow", **side}))
    return with_sidecar_facts(load_sidecar_manifest(tmp_path, "flowx"), tmp_path)


def test_good_page_and_topics_reach_the_manifest(tmp_path: Path) -> None:
    m = _load(tmp_path, {"page": {"menu": "flow", "main": "flow"}, "topics": ["runs", "feed"]})
    assert dict(m.page) == {"menu": "flow", "main": "flow"} and m.page_problem == "" and m.topics == ("runs", "feed")


def test_bad_view_name_drops_only_the_page(tmp_path: Path) -> None:
    m = _load(tmp_path, {"page": {"menu": "flow", "main": "nope"}, "topics": ["runs"]})
    assert m.page is None and "does not ship" in m.page_problem and m.topics == ("runs",) and m.views


def test_view_without_panel_surface_drops_the_page(tmp_path: Path) -> None:
    m = _load(tmp_path, {"page": {"menu": "ov", "main": "flow"}})
    assert m.page is None and "panel" in m.page_problem


def test_unknown_page_key_is_ignored(tmp_path: Path) -> None:
    m = _load(tmp_path, {"page": {"menu": "flow", "main": "flow", "future": 1}})
    assert dict(m.page) == {"menu": "flow", "main": "flow"}


def test_bad_duplicate_and_surplus_topics_are_dropped(tmp_path: Path) -> None:
    names = ["runs", "runs", "Bad Name", 5] + [f"t{i}" for i in range(9)]
    m = _load(tmp_path, {"topics": names})
    assert m.topics == ("runs",) + tuple(f"t{i}" for i in range(7)) and len(m.topics) == 8


def test_no_declaration_is_the_old_plugin(tmp_path: Path) -> None:
    m = _load(tmp_path, {})
    assert m.page is None and m.page_problem == "" and m.topics == ()
