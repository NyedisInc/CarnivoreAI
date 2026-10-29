
from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.core.flow_data import feed
from src.cplugs.flow import mcp, store
from src.core.flow_data.collect import build
from src.cplugs.host.activity_reader import ActivityReader
from tests.python.cplugs.flow import fixture as fx

NOW = fx.BASE + 4 * 3600
V90_CROSSTALK = {"landed_at", "landed_anchor", "delivery_path", "spawn_task", "agent_sent"}


@pytest.fixture()
def reader(tmp_path, monkeypatch):
    made = fx.make_install(tmp_path)
    core = sqlite3.connect(next((tmp_path / "state").glob("carnivore.db")))
    tables = {r[0] for r in core.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns = {r[1] for r in core.execute("PRAGMA table_info(crosstalk_messages)")}
    core.close()
    assert not tables & {"agent_spawn_links", "mcp_events"} and not columns & V90_CROSSTALK
    monkeypatch.setattr(ActivityReader, "_transcript_path", lambda self, conv: next((str(p) for p in made["paths"].values() if p.stem == conv), None))
    return ActivityReader(made["state_dir"])


def test_the_reader_reports_the_missing_core_data_and_answers_empty(reader):
    sources = reader.sources()
    assert (sources["core"], sources["huddle"]) == ("ok", "ok")
    opt = sources["optional"]
    assert opt["spawn_links"] is False and opt["mcp_events"] is False
    assert opt["write_actors"] is False and opt["huddle_source_item"] is False
    assert not set(opt["crosstalk_columns"]) & V90_CROSSTALK
    assert reader.spawn_links([fx.D, fx.F]) == []
    assert reader.mcp_events([fx.APP[fx.F]], fx.BASE, NOW) == []
    held = reader.huddle_item(395)
    assert held is not None and held["actors"] == [] and "source_item_id" not in held["item"]


def test_the_run_builds_from_inference(reader):
    run = build.build_run(reader, "huddle_item", "395", now=NOW)
    assert run["lanes"] and run["edges"]
    docker = next(lane for lane in run["lanes"] if lane["id"] == f"s:{fx.D}")
    assert docker["spawned_by"]["basis"] == "contact"
    assert "mcp_events" not in run
    crosstalk = [e for e in run["edges"] if e["kind"] == "crosstalk"]
    assert crosstalk and all(e["delivery_path"] is None and e["spawn_task"] is False for e in crosstalk)
    assert feed.page(run, None)["items"]


def test_flow_get_answers_without_the_core_data(reader, monkeypatch):
    monkeypatch.setattr(store, "load", lambda *a, **k: None)
    monkeypatch.setattr(store, "save", lambda *a, **k: None)
    ctx = SimpleNamespace(activity=reader, storage=None)
    answer = asyncio.run(mcp.flow_get(ctx, None, {"seed": "huddle_item", "id": 395, "refresh": True}))
    run = json.loads(answer["content"][0]["text"])
    assert run["lanes"] and run["edges"] and "mcp_events" not in run
