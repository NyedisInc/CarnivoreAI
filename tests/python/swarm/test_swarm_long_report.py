
from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_1425_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_1425_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.mcp.caller import AgentCaller
from src.core.swarm import delivery, reports, spawn, store, thread_port
from src.cplugs.host import runtime
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from tests.python.cplugs.owner import turn_on


def test_a_3000_character_report_posts_whole_in_the_thread(tmp_path: Path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, CURRENT_SCHEMA_VERSION)
        boss = store.create_agent(conn, slug="boss", rank="project", job="j", display_name="Boss", repo_dir=str(tmp_path), effort="high")
        fixer = store.create_agent(conn, slug="fixer", rank="feature", job="fix the cap", display_name="Fixer",
                                   repo_dir=str(tmp_path), effort="high", parent_id=boss["id"])
    host = runtime.install(FastAPI(), tmp_path)
    host.publish = lambda topic: None
    turn_on(host)
    port = TaskManagerSwarmPort(host.context("huddle"))
    thread_port.register(port)
    told = []

    async def parent_agent(view, caller):
        return fixer

    async def deliver_text(app_state, agent_id, text, **kw):
        told.append((agent_id, text))
        return "delivered"

    monkeypatch.setattr(spawn, "parent_agent", parent_agent)
    monkeypatch.setattr(delivery, "deliver_text", deliver_text)
    summary = "\n".join(f"line {n:04d} " + "x" * 50 for n in range(52))[:3000]
    assert len(summary) == 3000
    try:
        view = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        rid = asyncio.run(reports.report(view, AgentCaller("ses_1", "cloude_f", "ses_1"), {"summary": summary}))["report_id"]
        entries = asyncio.run(port.read_thread(fixer["thread_key"], 50))
        items = port._store().list_items(fixer["thread_key"])["items"]
    finally:
        thread_port.register(None)
    card = next(i for i in items if i["swarm_ref"] == f"report:{rid}")
    assert len(card["text"]) <= 2000 and card["text"].endswith("...") and summary.startswith(card["text"][:-3])
    assert [e["text"] for e in entries if e["kind"] == "agent"] == [summary]
    assert told and told[0][0] == boss["id"] and summary in told[0][1]
