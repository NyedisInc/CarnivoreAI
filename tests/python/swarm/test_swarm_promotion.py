
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s5_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s5_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.crosstalk import bus, store as crosstalk_store
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp import swarm_tools
from src.core.mcp.caller import AgentCaller
from src.core.swarm import body, body_create, create, delivery, desk, promotion, reports, spawn, promotion_store, store, thread_port, wake_prompt
from src.core.swarm.facade import SwarmFacade
from src.cplugs.sdk.swarm import SwarmError

TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


class Port:

    def __init__(self) -> None:
        self.cards, self.traffic, self.closed, self.archived = [], [], [], []

    async def ensure_thread(self, key, title): ...
    async def settle_cards(self, ref, **kw): ...
    async def post_card(self, key, kind, title, text, ref):
        self.cards.append((key, kind, ref))
        return len(self.cards)
    async def post_traffic(self, key, text, ref):
        self.traffic.append((key, ref))
        return f"huddle:msg:{len(self.traffic)}"
    async def close_card(self, item_id, state): self.closed.append((item_id, state))
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
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("hi\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "init")
    port = Port()
    thread_port.register(port)
    slept, woke = [], []

    async def deliver_text(app_state, agent_id, text, **kw):
        return "delivered"

    async def sleep(app_state, agent_id, reason="sleep"):
        slept.append((agent_id, reason))
        await body.run_db(lambda c: store.cas_state(c, agent_id, "awake", "asleep"))
        return body.SleepResult("asleep")

    async def wake(app_state, agent_id, reason, authority, **kw):
        woke.append((agent_id, reason))
        await body.run_db(lambda c: store.cas_state(c, agent_id, "asleep", "awake"))

    monkeypatch.setattr(delivery, "deliver_text", deliver_text)
    monkeypatch.setattr(body, "sleep", sleep)
    monkeypatch.setattr(body, "wake", wake)
    rows, agents = {}, {}

    def make(slug, rank, parent=None, task_type=None, **kw):
        with closing(connect(db_path_for(tmp_path / "state"), create=False)) as conn:
            conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin,"
                         " lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 1788821572, ?, 't', 'created', 'running',"
                         " '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (f"uuid-{slug}", f"cloude_{slug}", str(repo)))
            rows[slug] = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{slug}",)).fetchone()[0]
            row = store.create_agent(conn, slug=slug, rank=rank, job=f"job of {slug}", display_name=slug.title(), repo_dir=str(repo),
                                     effort="high", parent_id=parent, goal=f"goal of {slug}", task_type=task_type, **kw)
            store.set_session_row(conn, row["id"], rows[slug])
            store.cas_state(conn, row["id"], "asleep", "awake")
            agents[slug] = store.get_agent(conn, row["id"])
        if rank != "project":
            body_create.write_files(tmp_path / "state", agents[slug], "Boss")
        return agents[slug]

    with closing(connect(db_path_for(tmp_path / "state"), create=False)) as conn:
        project = body_create.register_project(conn, str(repo), "repo")
    boss = make("boss", "project", project_id=project["id"])
    yield SimpleNamespace(state=tmp_path / "state", repo=repo, port=port, slept=slept, woke=woke, agents=agents, rows=rows,
                          boss=boss, project=project, add_task=lambda slug, task_type="refactor": make(slug, "task", boss["id"], task_type))
    thread_port.register(None)


def _view(env, slug: str):
    info = SimpleNamespace(session=SimpleNamespace(id=f"ses_{slug}"), tmux_session=f"cloude_{slug}", session_row_id=env.rows[slug])

    async def infos():
        return [info]

    view = SimpleNamespace(list_session_infos=infos, app=SimpleNamespace(state=SimpleNamespace()), fresh=lambda: view)
    return view, AgentCaller(session_id=f"ses_{slug}", tmux_name=f"cloude_{slug}", current_session_id=f"ses_{slug}")


def _db(env, work):
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        return work(conn)


def _finish(env, slug: str) -> str:
    view, caller = _view(env, slug)
    rid = asyncio.run(reports.report(view, caller, {"summary": f"{slug} refactored the module", "done_items": ["one"]}))["report_id"]
    view, caller = _view(env, "boss")
    return asyncio.run(reports.accept(view, caller, {"report_id": rid, "decision": "accept"}))["outcome"]


def _result(answer: dict) -> dict:
    return json.loads(answer["content"][0]["text"])


def _exclude_text(env) -> str:
    path = Path(git(env.repo, "rev-parse", "--git-path", "info/exclude").strip())
    return (path if path.is_absolute() else env.repo / path).read_text()


def test_fifth_accepted_report_promotes_and_flip_back_reverses_it(env, monkeypatch):
    slug = "t5"
    local, proj = env.repo / ".claude/agent-memory-local" / slug, env.repo / ".claude/agent-memory" / slug
    assert _db(env, lambda c: promotion_store.promotion_threshold(c, env.project["id"])) == 5
    for n in range(1, 5):
        env.add_task(f"t{n}")
        assert _finish(env, f"t{n}") == "torn_down"
    t5 = env.add_task(slug)
    assert _db(env, lambda c: promotion_store.promotion_standing(c, t5)) == (4, 5)
    question = _db(env, lambda c: c.execute("INSERT INTO swarm_questions (text, state, answer_text, created_at) VALUES "
                                            "('which logger?', 'answered', 'use structlog', '2026-10-05T10:00:00Z')").lastrowid)
    _db(env, lambda c: c.execute("INSERT INTO swarm_question_askers (question_id, agent_id, asked_at) VALUES (?, ?, '2026-10-05T10:00:00Z')",
                                 (question, env.agents["t1"]["id"])))

    assert _finish(env, slug) == "promotion_candidate"
    row = _db(env, lambda c: store.get_agent(c, t5["id"]))
    assert row["state"] == "asleep" and row["torn_down_at"] is None and local.is_dir()
    boss_desk = _db(env, lambda c: desk.gather(c, env.boss))
    assert [c["id"] for c in boss_desk.candidates] == [t5["id"]]
    assert "promotion candidates" in wake_prompt.render_desk(env.boss, "crosstalk", "", boss_desk) and "5 accepted reports of 5" in "\n".join(desk.render(boss_desk))

    view, caller = _view(env, "boss")
    other = env.add_task("other", "docs")
    with pytest.raises(swarm_tools.ToolError, match="0 of 5 accepted reports"):
        asyncio.run(swarm_tools.swarm_promote(view, caller, {"agent_id": other["id"]}))
    _db(env, lambda c: c.execute("UPDATE swarm_reports SET summary = ? WHERE id = 1", (f"leaked {TOKEN}",)))
    with pytest.raises(swarm_tools.ToolError, match="specialty is required"):
        asyncio.run(swarm_tools.swarm_promote(view, caller, {"agent_id": t5["id"]}))
    with pytest.raises(swarm_tools.ToolError, match="seed digest cannot be written"):
        asyncio.run(swarm_tools.swarm_promote(view, caller, {"agent_id": t5["id"], "specialty": "Refactoring"}))
    assert local.is_dir() and not proj.exists() and _db(env, lambda c: store.get_agent(c, t5["id"]))["rank"] == "task"
    _db(env, lambda c: c.execute("UPDATE swarm_reports SET summary = 't1 refactored the module' WHERE id = 1"))

    _db(env, lambda c: c.execute("UPDATE sessions SET claude_session_uuid = 'conv-1' WHERE id = ?", (env.rows[slug],)))
    _db(env, lambda c: c.execute(
        "INSERT INTO transcript_files (path, family, root, source_path, conversation_id, kind, size, mtime_ns, first_seen, last_seen, "
        "changed_at) VALUES ('/tmp/conv-1.jsonl', 'claude', '/tmp', '/tmp/conv-1.jsonl', 'conv-1', 'conversation', 1, 1, 'n', 'n', 'n')"))
    monkeypatch.setattr(body, "_has_open_work", lambda conn, agent: True)
    assert _db(env, lambda c: body._resolve_mode(c, row, "auto")) == "resume"

    result = _result(asyncio.run(swarm_tools.swarm_promote(view, caller, {"agent_id": t5["id"], "specialty": "Refactoring"})))
    assert result["commit"]["status"] == "committed" and result["seed"] == f".claude/agent-memory/{slug}/seed-from-runs.md"
    promoted = _db(env, lambda c: store.get_agent(c, t5["id"]))
    assert promoted["rank"] == "feature" and promoted["memory_scope"] == "project" and promoted["slug"] == slug
    assert promoted["display_name"] == "Refactoring" and promoted["specialty"] == "Refactoring"
    assert not local.exists() and (proj / "MEMORY.md").is_file() and (proj / "swarm.json").read_text().count('"rank": "feature"') == 1
    assert json.loads((proj / "swarm.json").read_text())["parent_slug"] == env.boss["slug"]
    assert f"/.claude/agents/{slug}.md" not in _exclude_text(env) and f"/.claude/agent-memory-local/{slug}/" not in _exclude_text(env)
    assert "memory: project" in (env.repo / f".claude/agents/{slug}.md").read_text()
    seed = (proj / "seed-from-runs.md").read_text()
    assert seed.count("## run ") == 5 and "goal: goal of t1" in seed and "t3 refactored the module" in seed
    assert "question: which logger?" in seed and "answer: use structlog" in seed and "transcript: (not in the manifest)" in seed and "transcript: /tmp/conv-1.jsonl" in seed
    assert git(env.repo, "log", "-1", "--format=%s") == f"swarm: {slug} promoted to a feature agent\n"
    assert git(env.repo, "rev-parse", "HEAD").strip() == result["commit"]["sha"]
    tracked = git(env.repo, "ls-tree", "-r", "--name-only", "HEAD").split()
    assert {f".claude/agent-memory/{slug}/MEMORY.md", f".claude/agent-memory/{slug}/seed-from-runs.md", f".claude/agents/{slug}.md",
            f".codex/agents/{slug}.toml"} <= set(tracked)
    promo = _db(env, lambda c: promotion_store.live_promotion(c, t5["id"]))
    assert promo["task_type"] == "refactor" and promo["commit_sha"] == result["commit"]["sha"] and promo["receipt_card_ref"]
    assert env.port.cards[-1] == (env.boss["thread_key"], "question", f"promotion:{promo['id']}")
    events = asyncio.run(promotion.promoted_events(env.boss, 10))
    assert [e["event"] for e in events] == ["promoted"] and events[0]["id"] == f"ev:promoted:promotion:{promo['id']}"
    assert _db(env, lambda c: body._resolve_mode(c, promoted, "auto")) == "fresh"
    assert _db(env, lambda c: body._resolve_mode(c, promoted, "resume")) == "resume"
    own = _db(env, lambda c: desk.gather(c, promoted))
    assert own.seed_path == str(proj / "seed-from-runs.md") and "distill" in "\n".join(desk.render(own))
    assert _db(env, lambda c: desk.gather(c, env.boss)).candidates == []

    async def no_create(req):
        raise AssertionError("a promoted task type mints no agent")

    sent = []

    async def identities(view_, caller_, to):
        return {"key": "k-boss", "epoch": 1}, {"key": "k-t5", "epoch": 1, "id": to}

    async def send(view_, caller_, **kw):
        sent.append(kw["to"])
        return {"id": "m1"}

    monkeypatch.setattr(create, "create_agent", no_create)
    monkeypatch.setattr(bus, "identities", identities)
    monkeypatch.setattr(bus, "send", send)
    monkeypatch.setattr(crosstalk_store, "grant_contact", lambda *a, **kw: None)
    args = {"job": "refactor the parser", "goal": "split it", "task_type": "refactor", "rank": "task", "effort": "medium"}
    plan = asyncio.run(spawn.prepare(view, caller, args))
    assert plan.target["id"] == t5["id"] and "goes to the feature agent Refactoring" in spawn.owner_summary(plan)
    routed = asyncio.run(spawn.run(view, caller, plan))
    assert routed["agent_id"] == t5["id"] and routed["routed_to_promoted"] and (t5["id"], "spawn") in env.woke and sent == [f"agent:{t5['id']}"]
    assert asyncio.run(spawn.prepare(view, caller, {**args, "task_type": "other-type"})).target is None

    facade = SwarmFacade(env.state, lambda: asyncio.sleep(0, []), SimpleNamespace())
    asyncio.run(facade.card_decided(f"promotion:{promo['id']}", "approve", "", ""))
    assert _db(env, lambda c: store.get_agent(c, t5["id"]))["rank"] == "feature"
    asyncio.run(facade.card_decided(f"promotion:{promo['id']}", "decline", "", ""))
    back = _db(env, lambda c: store.get_agent(c, t5["id"]))
    assert back["rank"] == "task" and back["memory_scope"] == "local" and back["torn_down_at"] is None and back["slug"] == slug
    assert local.is_dir() and (local / "seed-from-runs.md").is_file() and not proj.exists()
    assert f"/.claude/agents/{slug}.md" in _exclude_text(env) and f"/.claude/agent-memory-local/{slug}/" in _exclude_text(env)
    assert "memory: local" in (env.repo / f".claude/agents/{slug}.md").read_text()
    flipped = _db(env, lambda c: promotion_store.get_promotion(c, promo["id"]))
    assert flipped["flipped_back_at"] and flipped["flip_commit_sha"] == git(env.repo, "rev-parse", "HEAD").strip()
    assert git(env.repo, "log", "-1", "--format=%s") == f"swarm: {slug} flipped back to a task agent\n"
    still = set(git(env.repo, "ls-tree", "-r", "--name-only", "HEAD").split())
    assert not [f for f in still if slug in f] and "README.md" in still
    assert git(env.repo, "status", "--porcelain").strip() == ""
    assert (int(promo["receipt_card_ref"]), "flipped") in env.port.closed
    assert json.loads((env.repo / f".claude/agent-memory-local/{slug}/swarm.json").read_text())["parent_slug"] == env.boss["slug"]
    assert _db(env, lambda c: promotion_store.promoted_agent(c, env.boss["id"], "refactor")) is None
    assert _db(env, lambda c: body._resolve_mode(c, back, "auto")) == "fresh"
    assert asyncio.run(spawn.prepare(view, caller, args)).target is None
    assert _db(env, lambda c: promotion_store.promotion_standing(c, back))[0] == 0
    with pytest.raises(promotion.PromotionRefused, match="already flipped back"):
        asyncio.run(promotion.flip_back(SimpleNamespace(), t5["id"]))
    with pytest.raises(SwarmError):
        asyncio.run(facade.card_decided("promotion:999", "decline", "", ""))
    kinds = [e["id"] for e in asyncio.run(promotion.promoted_events(env.boss, 10))]
    assert kinds == [f"ev:promoted:promotion:{promo['id']}", f"ev:promoted:promotion:{promo['id']}:flipped"]


def test_declining_a_candidate_tears_it_down_and_the_threshold_is_a_project_setting(env):
    assert _db(env, lambda c: promotion_store.set_promotion_threshold(c, env.project["id"], 2)) == 2
    assert _db(env, lambda c: promotion_store.promotion_threshold(c, env.project["id"])) == 2
    with pytest.raises(Exception):
        _db(env, lambda c: promotion_store.set_promotion_threshold(c, env.project["id"], 0))
    env.add_task("a1")
    assert _finish(env, "a1") == "torn_down"
    a2 = env.add_task("a2")
    assert _finish(env, "a2") == "promotion_candidate"
    view, caller = _view(env, "boss")
    out = _result(asyncio.run(swarm_tools.swarm_promote(view, caller, {"agent_id": a2["id"], "decision": "teardown"})))
    assert out["outcome"] == "torn_down" and _db(env, lambda c: store.get_agent(c, a2["id"]))["state"] == "torn_down"
    assert not (env.repo / ".claude/agent-memory-local/a2").exists()
