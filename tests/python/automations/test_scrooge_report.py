from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import automation_run_routes, session_crud_routes
from src.core.automations import models as m
from src.core.automations import recipes
from src.core.automations.targets import recipe as recipe_target
from src.core.byoai import gateway as gateway_module
from src.core.byoai.contracts import AgentResult, NotConfigured, Usage
from src.core.db import db_path_for
from src.core.stats import config, project_groups
from src.core.stats.plugin.extract import project_key
from src.core.stats.store import StatsStore
from tests.stats import seed

NOW = datetime.now(timezone.utc)
STAMP = int((NOW - timedelta(days=1)).timestamp()) // 60 * 60
FAKE_KEY = "ghp_" + "aB3xY9" * 6
GLOBAL_RULES = "".join(f"global rule number {i}\n" for i in range(6))


def _usage(db, conv, path, model, cost):
    seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (STAMP, "local", "claude", conv, project_key(str(path)), model, "session",
                  10, 0, 0, 5, cost, "v1", 1, 1, 0, "ok"))


@pytest.fixture
def world(tmp_path, monkeypatch):
    tmp = tmp_path.resolve()
    home = tmp / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    (home / ".claude" / "CLAUDE.md").write_text(GLOBAL_RULES)
    project_groups.forget()
    a, b = tmp / "proj" / "A", tmp / "proj" / "B"
    for folder in (a, b):
        folder.mkdir(parents=True)
    (a / "CLAUDE.md").write_text(GLOBAL_RULES + f"deploy token is {FAKE_KEY}\n")
    store = StatsStore(tmp / "state")
    store.initialize()
    config.ensure_schema(store)
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    path = db_path_for(store.state_dir)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, root TEXT, raw_path TEXT, display_name TEXT, archived_at TEXT)")
        db.execute("CREATE TABLE sessions (project_id INTEGER, working_dir TEXT, last_work_at TEXT)")
        for pid, (name, folder) in enumerate((("A", a), ("B", b)), start=1):
            db.execute("INSERT INTO projects VALUES (?,?,?,?,NULL)", (pid, str(folder), str(folder), name))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (pid, str(folder), (NOW - timedelta(days=2)).isoformat()))
    with store.connect() as db:
        _usage(db, "a", a, "claude-opus-4-1", 400_000_000_000)
        _usage(db, "b", b, "claude-sonnet-4-5", 5_000_000_000)

    def open_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(recipes, "_open_db", open_db)
    emitted = []
    monkeypatch.setattr(recipe_target.alert_service, "raise_alert", lambda key, **kw: emitted.append((key, kw)))
    ctx = SimpleNamespace(app_state=SimpleNamespace(stats_store=store))
    return SimpleNamespace(ctx=ctx, emitted=emitted, a=a, tmp=tmp)


AUTOMATION = {"target": {"kind": "recipe", "recipe": "scrooge", "params": {}}, "delivery": {"notify": True, "notify_on": None}}
RUN = {"run_id": "run_1"}


def _ai_reply(title="ai spotted extra spend"):
    finding = {"project": "A", "lever": "L2", "severity": "high", "title": title, "evidence": "sub-agent spend is high",
               "est_saving_usd_month": 12.5, "fix_prompt": "Look at the sub-agent use in this project and propose bounds."}
    return AgentResult(text=json.dumps({"findings": [finding]}), usage=Usage(cost_usd=0.12), raw={})


def test_scrooge_report(world, monkeypatch):
    seen = {}

    async def fake_agent(ref, prompt, **options):
        seen.update(ref=ref, prompt=prompt, options=options)
        return _ai_reply()
    monkeypatch.setattr(gateway_module, "agent", fake_agent)

    outcome = asyncio.run(recipe_target.run(world.ctx, AUTOMATION, RUN))

    assert seen["ref"] == "automations.scrooge" and seen["options"]["max_budget_usd"] == 1.0
    report = outcome.report
    assert outcome.status == m.SUCCEEDED and report["schema"] == "scrooge/1"
    assert {p["name"] for p in report["projects"]} == {"A", "B"} and len(report["levers"]) == 7
    sources = {f["source"] for f in report["findings"]}
    assert sources == {"numbers", "ai"}
    ids = [f["finding_id"] for f in report["findings"]]
    assert len(ids) == len(set(ids))
    assert report["ai"]["status"] == "ok" and report["ai"]["cost_usd"] == 0.12 and outcome.cost_usd == 0.12
    assert FAKE_KEY not in seen["prompt"] and "[redacted]" in seen["prompt"]
    assert [k for k, _ in world.emitted] == ["automation.report.run_1"]
    assert world.emitted[0][1]["actions"][0]["href"] == "#automations/run/run_1"

    ai_finding = next(f for f in report["findings"] if f["source"] == "ai")
    created = []

    async def fake_create(request, body):
        created.append(body)
        return {"id": "ses_x"}
    monkeypatch.setattr(session_crud_routes, "create_session", fake_create)
    store = SimpleNamespace(run=lambda run_id: {"report": report})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(automation_store=store)))
    asyncio.run(automation_run_routes.start_fix_session(request, "run_1", ai_finding["finding_id"]))
    assert created[0].opening_prompt == ai_finding["fix_prompt"] and created[0].working_dir == str(world.a)
    assert created[0].label.startswith("scrooge fix: ")
    with pytest.raises(HTTPException) as gone:
        asyncio.run(automation_run_routes.start_fix_session(request, "run_1", "nope"))
    assert gone.value.status_code == 404 and len(created) == 1


def test_scrooge_report_unrouted(world, monkeypatch):
    async def unrouted(ref, prompt, **options):
        raise NotConfigured("automations.scrooge has no connection chosen")
    monkeypatch.setattr(gateway_module, "agent", unrouted)

    outcome = asyncio.run(recipe_target.run(world.ctx, AUTOMATION, RUN))

    assert outcome.status == m.SUCCEEDED and outcome.report["ai"]["status"] == "ai_not_routed"
    assert outcome.report["findings"] and {f["source"] for f in outcome.report["findings"]} == {"numbers"}
    assert outcome.cost_usd is None
    assert [k for k, _ in world.emitted] == ["automation.report.run_1"]


def test_one_hour_cache_share_raises_no_finding():
    from src.core.automations.scrooge.report import numbers_findings
    project = {"project_id": 1, "name": "A", "share_pct": 5.0, "model_mix": [], "rule_files": [], "overlap": [],
               "cache_write_1h_share_pct": 100.0, "cache_write_1h": 50_000_000}
    assert numbers_findings([project]) == []
