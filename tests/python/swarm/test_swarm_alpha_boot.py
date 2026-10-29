
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s7c_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s7c_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import alpha, desk, routing, store, thread_port
from src.core.swarm.facade import SwarmFacade


class Port:

    def __init__(self) -> None:
        self.cards, self.threads, self.settled = [], [], []

    async def close_open_cards(self, key, prefix): ...
    async def ensure_thread(self, key, title):
        self.threads.append(key)

    async def settle_cards(self, ref, **kw):
        self.settled.append(ref)

    async def post_card(self, key, kind, title, text, ref):
        self.cards.append((key, kind, ref))
        return len(self.cards)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    state, root = tmp_path / "state", tmp_path / "carnivore-projects"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: root, raising=True)
    assert ensure_db_migrated(state).status == "ok"
    port = Port()
    thread_port.register(None)
    yield SimpleNamespace(state=state, root=root, port=port)
    thread_port.register(None)


def _db(env, work):
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        return work(conn)


def _alphas(env):
    return _db(env, lambda c: [dict(r) for r in c.execute("SELECT * FROM swarm_agents WHERE rank = 'alpha'")])


def _turn_on(env):
    async def go():
        SwarmFacade(env.state, lambda: asyncio.sleep(0, [])).register_thread_port(env.port)
        await asyncio.gather(*list(alpha._tasks))

    asyncio.run(go())


def test_turning_the_swarm_on_creates_folder_repo_project_and_one_asleep_alpha(env) -> None:
    folder = env.root / "Alpha"
    assert not folder.exists()
    _turn_on(env)
    (row,) = _alphas(env)
    assert row["state"] == "asleep" and row["session_row_id"] is None and row["thread_key"] == "all" and row["effort"] == "high"
    assert row["repo_dir"] == os.path.realpath(folder) and row["parent_id"] is None
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=folder, capture_output=True, text=True, check=True).stdout.strip()
    assert os.path.realpath(top) == os.path.realpath(folder)
    project = _db(env, lambda c: c.execute("SELECT id, company_id FROM projects WHERE root = ?", (os.path.realpath(folder),)).fetchone())
    assert project is not None and project["company_id"] is None and row["project_id"] == project["id"]
    assert env.port.threads == ["all"] and env.port.cards == []


def test_a_second_boot_creates_nothing(env) -> None:
    _turn_on(env)
    before = (_alphas(env), _db(env, lambda c: c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]))
    _turn_on(env)
    assert (_alphas(env), _db(env, lambda c: c.execute("SELECT COUNT(*) FROM projects").fetchone()[0])) == before
    assert len(before[0]) == 1


def test_with_the_swarm_off_nothing_is_created(env) -> None:
    assert not (env.root / "Alpha").exists() and _alphas(env) == []
    SwarmFacade(env.state, lambda: asyncio.sleep(0, [])).register_thread_port(None)
    assert not (env.root / "Alpha").exists() and _alphas(env) == []


def test_the_database_allows_only_one_live_alpha(env) -> None:
    import sqlite3
    _turn_on(env)
    with pytest.raises(sqlite3.IntegrityError):
        _db(env, lambda c: store.create_agent(c, slug="alpha-2", rank="alpha", job="j", display_name="A2", repo_dir=str(env.root / "x"), effort="high"))


def test_a_taken_folder_is_never_adopted_and_gets_one_info_card(env) -> None:
    folder = env.root / "Alpha"
    folder.mkdir(parents=True)
    (folder / "mine.txt").write_text("owner's file")
    _turn_on(env)
    assert _alphas(env) == [] and (folder / "mine.txt").read_text() == "owner's file" and not (folder / ".git").exists()
    assert env.port.cards == [("all", "info", alpha.FOLDER_CARD_REF)]
    _turn_on(env)
    assert env.port.settled == [alpha.FOLDER_CARD_REF] * 2 and len(env.port.cards) == 2


def test_alpha_is_the_top_memory_hop_and_her_desk_lists_the_work(env) -> None:
    _turn_on(env)

    def work(conn):
        a = alpha.live_alpha(conn)
        lone = store.create_agent(conn, slug="p1", rank="project", job="j", display_name="P1", repo_dir=str(env.root / "p1"), effort="high")
        chain = routing.chain_for(conn, lone)
        conn.execute("INSERT INTO swarm_suggestions (by_agent_id, kind, name, reason, state, created_at) VALUES (?, 'company', 'Acme', 'r', 'pending', '2026-10-05')", (a["id"],))
        return a, [t["rank"] for t in chain], desk.render(desk.gather(conn, a))

    a, ranks, lines = _db(env, work)
    assert ranks == ["alpha"] and any("no companies yet" in line for line in lines) and "  | Acme" in lines and lines.index("  | Acme") > lines.index(desk.DATA_HEADING)


def test_a_top_agent_still_named_with_the_old_default_becomes_sysop_and_a_typed_name_stays(env) -> None:
    _turn_on(env)
    assert _alphas(env)[0]["display_name"] == "SysOp"
    _db(env, lambda c: (c.execute("UPDATE swarm_agents SET display_name = 'Alpha' WHERE rank = 'alpha'"), c.commit()))
    _turn_on(env)
    assert _alphas(env)[0]["display_name"] == "SysOp"
    _db(env, lambda c: (c.execute("UPDATE swarm_agents SET display_name = 'Chief' WHERE rank = 'alpha'"), c.commit()))
    _turn_on(env)
    assert _alphas(env)[0]["display_name"] == "Chief"


def test_a_top_agent_job_still_holding_an_old_default_text_moves_to_the_current_one_and_a_typed_job_stays(env) -> None:
    _turn_on(env)
    for legacy in alpha.LEGACY_JOBS:
        _db(env, lambda c: (c.execute("UPDATE swarm_agents SET job = ? WHERE rank = 'alpha'", (legacy,)), c.commit()))
        _turn_on(env)
        assert _alphas(env)[0]["job"] == alpha.JOB and "swarm_suggest" in alpha.JOB
    _db(env, lambda c: (c.execute("UPDATE swarm_agents SET job = 'my own job' WHERE rank = 'alpha'"), c.commit()))
    _turn_on(env)
    assert _alphas(env)[0]["job"] == "my own job"
