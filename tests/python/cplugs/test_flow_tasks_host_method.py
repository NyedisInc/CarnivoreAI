
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from src.cplugs.host import flow_port
from src.cplugs.runtime import guards
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens

SCHEMA = ("CREATE TABLE work_items (id INTEGER PRIMARY KEY, list_key TEXT, text TEXT, state TEXT, updated_at REAL, deleted INTEGER DEFAULT 0, title TEXT);")


def _state(tmp_path: Path, rows) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    db = sqlite3.connect(state / "carnivore.db")
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO work_items VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()
    return state


def _dispatcher(state: Path) -> HostDispatcher:
    port = flow_port.FlowPort(lambda: state)
    return HostDispatcher(HostServices(activity=lambda row: None, flow_tasks=port.tasks), OwnerTokens())


def _call(dispatcher: HostDispatcher, params: dict, *granted: str):
    ctx = PluginContext(plugin_id="flowx", install_key="k", data_dir=Path("/nonexistent"), granted=frozenset(granted), tier="sideload")
    try:
        return asyncio.run(dispatcher.handle(ctx, "flow.tasks", params))
    except guards.Refused as exc:
        return exc


@pytest.fixture()
def tasks(tmp_path):
    rows = [(10, "8", "qnap backup\nmore text", "open", 100.0, 0, "Nightly Backup Broken"),
            (11, "8", "\n  first line of body\nsecond", "review", 300.0, 0, None),
            (12, "9", "x" * 500, "working", 200.0, 0, ""),
            (13, "8", "deleted backup item", "open", 400.0, 1, "Backup gone")]
    return _dispatcher(_state(tmp_path, rows))


def test_refused_without_flow_read(tasks):
    out = _call(tasks, {})
    assert isinstance(out, guards.Refused)


def test_ordering_deleted_and_shape(tasks):
    out = _call(tasks, {}, "flow.read")
    assert [t["id"] for t in out["tasks"]] == [11, 12, 10]
    assert out["tasks"][0] == {"id": 11, "number": None, "title": "first line of body", "state": "review", "list": "8", "updated": 300.0}
    assert len(out["tasks"][1]["title"]) == 120
    assert out["tasks"][2]["title"] == "Nightly Backup Broken"


def test_query_by_title_and_text_case_insensitive(tasks):
    assert [t["id"] for t in _call(tasks, {"query": "NIGHTLY"}, "flow.read")["tasks"]] == [10]
    assert [t["id"] for t in _call(tasks, {"query": "second"}, "flow.read")["tasks"]] == [11]
    assert _call(tasks, {"query": "backup gone"}, "flow.read")["tasks"] == []


def test_query_by_digits_matches_id(tasks):
    assert [t["id"] for t in _call(tasks, {"query": "12"}, "flow.read")["tasks"]] == [12]


def test_limit_clamped(tasks):
    assert len(_call(tasks, {"limit": 0}, "flow.read")["tasks"]) == 1
    assert len(_call(tasks, {"limit": -5}, "flow.read")["tasks"]) == 1
    assert len(_call(tasks, {"limit": 2}, "flow.read")["tasks"]) == 2
    assert len(_call(tasks, {"limit": 1000}, "flow.read")["tasks"]) == 3
    assert _call(tasks, {"limit": "x"}, "flow.read").code == "invalid_params"


def test_like_wildcards_are_literal(tasks):
    assert _call(tasks, {"query": "%"}, "flow.read")["tasks"] == []


def test_unavailable_without_a_store(tmp_path):
    out = _call(_dispatcher(tmp_path), {}, "flow.read")
    assert isinstance(out, guards.Refused) and out.code == "unavailable"
