
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s2b_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s2b_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, body_create, create, delivery, desk, project_agent, reports, store, thread_port, wake_prompt


class Port:

    def __init__(self) -> None:
        self.cards, self.traffic, self.closed, self.archived = [], [], [], []

    async def close_open_cards(self, key, prefix): ...
    async def ensure_thread(self, key, title): ...
    async def post_card(self, key, kind, title, text, ref):
        self.cards.append((key, kind, ref))
        return len(self.cards)
    async def post_traffic(self, key, text, ref):
        self.traffic.append((key, ref))
        return f"huddle:msg:{len(self.traffic)}"
    async def close_card(self, item_id, state): self.closed.append((item_id, state))
    async def open_card_id(self, key, ref):
        shut = {i for i, _ in self.closed}
        return next((n for n, c in enumerate(self.cards, 1) if c[0] == key and c[2] == ref and n not in shut), None)
    async def archive_thread(self, key): self.archived.append(key)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path / "state", raising=True)
    (tmp_path / "state").mkdir()
    assert ensure_db_migrated(tmp_path / "state").status == "ok"
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    port = Port()
    thread_port.register(port)
    told, slept = [], []

    async def deliver_text(app_state, agent_id, text, **kw):
        told.append((agent_id, kw.get("source")))
        return "delivered"

    async def sleep(app_state, agent_id, reason="sleep"):
        slept.append((agent_id, reason))
        await body.run_db(lambda c: store.cas_state(c, agent_id, "awake", "asleep"))
        return body.SleepResult("asleep")

    monkeypatch.setattr(delivery, "deliver_text", deliver_text)
    monkeypatch.setattr(body, "sleep", sleep)
    rows, agents = {}, {}
    with closing(connect(db_path_for(tmp_path / "state"), create=False)) as conn:
        def agent(slug, rank, parent=None, scope=None):
            conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin,"
                         " lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 1788821572, ?, 't', 'created', 'running',"
                         " '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (f"uuid-{slug}", f"cloude_{slug}", str(repo)))
            rows[slug] = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{slug}",)).fetchone()[0]
            row = store.create_agent(conn, slug=slug, rank=rank, job=f"job of {slug}", display_name=slug.title(), repo_dir=str(repo),
                                     effort="high", parent_id=parent, goal=f"goal of {slug}", task_type="refactor")
            store.set_session_row(conn, row["id"], rows[slug])
            store.cas_state(conn, row["id"], "asleep", "awake")
            agents[slug] = store.get_agent(conn, row["id"])
        agent("boss", "project")
        agent("fixer", "task", agents["boss"]["id"])
        agent("builder", "feature", agents["boss"]["id"])
    for slug in ("fixer", "builder"):
        body_create.write_files(tmp_path / "state", agents[slug], "Boss")
    yield SimpleNamespace(state=tmp_path / "state", repo=repo, port=port, told=told, slept=slept, agents=agents, rows=rows)
    thread_port.register(None)


def _view(env, slug: str):
    info = SimpleNamespace(session=SimpleNamespace(id=f"ses_{slug}"), tmux_session=f"cloude_{slug}", session_row_id=env.rows[slug])

    async def infos():
        return [info]

    view = SimpleNamespace(list_session_infos=infos, app=SimpleNamespace(state=SimpleNamespace()))
    return view, AgentCaller(session_id=f"ses_{slug}", tmux_name=f"cloude_{slug}", current_session_id=f"ses_{slug}")


def _db(env, work):
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        return work(conn)


def _report(env, slug: str) -> int:
    view, caller = _view(env, slug)
    return asyncio.run(reports.report(view, caller, {"summary": f"{slug} is done", "done_items": ["one", "two"]}))["report_id"]


def _accept(env, slug: str, report_id: int, decision: str = "accept"):
    view, caller = _view(env, slug)
    return asyncio.run(reports.accept(view, caller, {"report_id": report_id, "decision": decision}))


def test_accepting_a_task_report_tears_it_down_and_a_feature_agent_sleeps(env):
    fixer, builder, boss = env.agents["fixer"], env.agents["builder"], env.agents["boss"]
    definition, twin = env.repo / ".claude/agents/fixer.md", env.repo / ".codex/agents/fixer.toml"
    local = env.repo / ".claude/agent-memory-local/fixer"
    exclude = Path(git(env.repo, "rev-parse", "--git-path", "info/exclude").strip())
    exclude = exclude if exclude.is_absolute() else env.repo / exclude
    assert definition.is_file() and twin.is_file() and local.is_dir() and "fixer" in exclude.read_text()

    rid = _report(env, "fixer")
    assert env.port.cards[-1] == (fixer["thread_key"], "done", f"report:{rid}")
    assert env.port.traffic[-1] == (boss["thread_key"], f"report:{rid}") and (boss["id"], "report") in env.told
    pending = _db(env, lambda c: desk.gather(c, boss))
    assert [r["id"] for r in pending.reports] == [rid]
    assert f"report {rid} from Fixer" in wake_prompt.render_desk(boss, "crosstalk", "", pending)
    with pytest.raises(reports.ReportRefused, match="still waiting"):
        _report(env, "fixer")

    for who in ("builder", "fixer"):
        with pytest.raises(reports.ReportRefused, match="not from one of your own"):
            _accept(env, who, rid)
    assert _db(env, lambda c: store.get_report(c, rid))["state"] == "pending" and definition.is_file()

    assert _accept(env, "boss", rid)["outcome"] == "torn_down"
    assert not definition.exists() and not twin.exists() and not local.exists()
    assert "fixer" not in exclude.read_text()
    row = _db(env, lambda c: store.get_agent(c, fixer["id"]))
    assert row["state"] == "torn_down" and row["torn_down_at"]
    assert _db(env, lambda c: c.execute("SELECT archived_at FROM sessions WHERE id = ?", (env.rows["fixer"],)).fetchone()[0])
    assert env.port.archived == [fixer["thread_key"]] and (fixer["id"], "teardown") in env.slept
    assert _db(env, lambda c: store.get_report(c, rid))["state"] == "accepted"
    with pytest.raises(reports.ReportRefused, match="already decided"):
        _accept(env, "boss", rid)

    rid2 = _report(env, "builder")
    assert _accept(env, "boss", rid2)["outcome"] == "asleep"
    kept = _db(env, lambda c: store.get_agent(c, builder["id"]))
    assert kept["state"] == "asleep" and kept["torn_down_at"] is None
    assert (env.repo / ".claude/agent-memory/builder").is_dir() and (env.repo / ".claude/agents/builder.md").is_file()
    assert env.port.archived == [fixer["thread_key"]] and env.port.closed == [(int(_db(env, lambda c: store.get_report(c, rid2))["child_card_ref"]), "done")]


def test_turn_on_inits_the_repo_then_binds_the_project_thread_and_the_naming_card_renames(env, monkeypatch, tmp_path):
    woke = []

    async def wake(app_state, agent_id, reason, authority, **kw):
        woke.append((agent_id, reason, kw.get("orders")))
        await body.run_db(lambda c: store.cas_state(c, agent_id, "asleep", "awake"))

    monkeypatch.setattr(body, "wake", wake)
    plain = tmp_path / "plain"
    plain.mkdir()
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        loose = body_create.register_project(conn, str(plain), "plain")
    asyncio.run(project_agent.turn_on(SimpleNamespace(), loose["id"]))
    assert (plain / ".git").is_dir() and woke[-1][1] == "spawn"
    assert not [c for c in env.port.cards if c[2].startswith("gitinit:")]
    made = _db(env, lambda c: store.get_project_agent(c, loose["id"]))
    assert made["rank"] == "project" and made["thread_key"] == str(loose["id"]) and made["naming_state"] == "none"
    with pytest.raises(project_agent.TurnOnError, match="already on"):
        asyncio.run(project_agent.turn_on(SimpleNamespace(), loose["id"], None))

    from src.core.swarm import settings as swarm_settings

    monkeypatch.setattr(swarm_settings, "naming_family_on", lambda: True)
    asyncio.run(project_agent.propose_naming(made, "Norse gods", "Odin", "short names that sort well"))
    assert env.port.cards[-1] == (made["thread_key"], "waiting", f"naming:{made['id']}")
    child = asyncio.run(create.create_agent(
        {"repo_dir": str(plain), "job": "swap models", "rank": "task", "parent_id": made["id"]}))
    assert child["display_name"] == "Swap Models"
    asyncio.run(project_agent.decide(SimpleNamespace(), f"naming:{made['id']}", True))
    named = _db(env, lambda c: store.get_agent(c, made["id"]))
    assert named["naming_state"] == "approved" and named["display_name"] == "Odin (plain)"
    child2 = asyncio.run(create.create_agent(
        {"repo_dir": str(plain), "job": "fix login", "rank": "task", "parent_id": made["id"], "display_name": "Loki"}))
    assert child2["display_name"] == "Loki"


def test_the_closeout_default_accepts_an_undecided_report_so_the_task_agent_is_torn_down(env):
    from datetime import datetime, timedelta, timezone

    from src.core.swarm import closeout

    fixer, boss = env.agents["fixer"], env.agents["boss"]
    rid = _report(env, "fixer")
    assert asyncio.run(closeout.sweep(SimpleNamespace())) == 0
    assert asyncio.run(closeout.sweep(SimpleNamespace(), now=datetime.now(timezone.utc) + timedelta(minutes=16))) == 1
    assert _db(env, lambda c: store.get_report(c, rid))["state"] == "accepted"
    assert _db(env, lambda c: store.get_agent(c, fixer["id"]))["state"] == "torn_down"
    assert env.port.cards[-1] == (boss["thread_key"], "info", f"closeout:{rid}")


def test_no_task_agent_lingers_the_backstop_sleeps_an_undecided_one_and_an_accept_tears_it_down(env, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from src.core.swarm import closeout
    from src.core.swarm.settings import SwarmConfig

    monkeypatch.setattr(closeout.settings, "read_current", lambda: SwarmConfig(closeout_default="sleep"))

    fixer, boss = env.agents["fixer"], env.agents["boss"]
    rid = _report(env, "fixer")
    assert asyncio.run(closeout.sweep(SimpleNamespace())) == 0
    assert _db(env, lambda c: store.get_agent(c, fixer["id"]))["state"] == "awake"
    assert _db(env, lambda c: desk.gather(c, boss)).closeouts == []

    later = datetime.now(timezone.utc) + timedelta(minutes=16)
    assert asyncio.run(closeout.sweep(SimpleNamespace(), now=later)) == 1
    assert (fixer["id"], "auto_sleep") in env.slept
    assert _db(env, lambda c: store.get_agent(c, fixer["id"]))["state"] == "asleep"
    assert env.port.cards[-1] == (boss["thread_key"], "info", f"closeout:{rid}")
    assert asyncio.run(closeout.sweep(SimpleNamespace(), now=later)) == 0
    on_desk = _db(env, lambda c: closeout.waiting(c, parent_id=boss["id"]))
    assert [(a["id"], a["report_id"]) for a in on_desk] == [(fixer["id"], rid)]
    text = "\n".join(desk.render(desk.Desk(closeouts=on_desk)))
    assert f"Fixer (agent {fixer['id']}, asleep): report {rid}" in text and "swarm_promote" in text

    assert _accept(env, "boss", rid)["outcome"] == "torn_down"
    live_tasks = _db(env, lambda c: [a for a in store.list_agents(c) if a["rank"] == "task"])
    assert live_tasks == [] and _db(env, lambda c: closeout.waiting(c, parent_id=boss["id"])) == []
