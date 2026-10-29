
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s7b_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s7b_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.companies import accounts, store as companies
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_steps import run_chain
from src.core.mcp import swarm_tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.swarm import body, company_agent, desk, profiles, project_agent, store, thread_port, wake_prompt
from src.core.swarm.facade import SwarmFacade


class Port:

    def __init__(self) -> None:
        self.cards = []

    async def close_open_cards(self, key, prefix): ...
    async def ensure_thread(self, key, title): ...
    async def settle_cards(self, ref, **kw): ...
    async def post_card(self, key, kind, title, text, ref):
        self.cards.append((key, kind, ref, text))
        return len(self.cards)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    state, root = tmp_path / "state", tmp_path / "carnivore-projects"
    state.mkdir()
    root.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: root, raising=True)
    assert ensure_db_migrated(state).status == "ok"
    port, woke = Port(), []
    thread_port.register(port)

    async def wake(app_state, agent_id, reason, authority, orders="", **kw):
        woke.append((agent_id, reason))

    monkeypatch.setattr(body, "wake", wake)
    rows, agents = {}, {}
    with closing(connect(db_path_for(state), create=False)) as conn:
        acme = companies.create_company(conn, "Acme")

        def agent(slug, rank, **kw):
            conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin,"
                         " lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 1788821572, ?, 't', 'created', 'running',"
                         " '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (f"uuid-{slug}", f"cloude_{slug}", str(tmp_path)))
            rows[slug] = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{slug}",)).fetchone()[0]
            row = store.create_agent(conn, slug=slug, rank=rank, job=f"job of {slug}", display_name=slug.title(),
                                     repo_dir=str(tmp_path / slug), effort="high", **kw)
            store.set_session_row(conn, row["id"], rows[slug])
            agents[slug] = store.get_agent(conn, row["id"])

        agent("alpha", "alpha")
        agent("acmeboss", "company", company_id=acme["id"])
        agent("proj", "project")
    yield SimpleNamespace(state=state, root=root, port=port, woke=woke, rows=rows, agents=agents, acme=acme)
    thread_port.register(None)


def _db(env, work):
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        return work(conn)


def _suggest(env, slug, **args):
    info = SimpleNamespace(session=SimpleNamespace(id=f"ses_{slug}"), tmux_session=f"cloude_{slug}", session_row_id=env.rows[slug])

    async def infos():
        return [info]

    view = SimpleNamespace(list_session_infos=infos, app=SimpleNamespace(state=SimpleNamespace()))
    caller = AgentCaller(session_id=f"ses_{slug}", tmux_name=f"cloude_{slug}", current_session_id=f"ses_{slug}")
    return asyncio.run(swarm_tools.swarm_suggest(view, caller, args))


def _decide(env, ref, decision):
    asyncio.run(SwarmFacade(env.state, lambda: asyncio.sleep(0, []), SimpleNamespace()).card_decided(ref, decision, "", ""))


def _counts(env):
    rows = _db(env, lambda c: tuple(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("projects", "swarm_agents", "companies")))
    return rows + (sorted(p.name for p in env.root.iterdir()),)


def _suggestion_state(env):
    return _db(env, lambda c: c.execute("SELECT state FROM swarm_suggestions").fetchone()[0])


def _is_repo_root(path: Path) -> bool:
    top = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    return top.returncode == 0 and os.path.realpath(top.stdout.strip()) == os.path.realpath(path)


def test_project_approval_creates_folder_repo_project_and_agent_and_nothing_before(env):
    before = _counts(env)
    _suggest(env, "acmeboss", kind="project", name="Billing API", reason="the roadmap needs billing")
    key, kind, ref, _text = env.port.cards[-1]
    assert (key, kind) == ("all", "question") and ref.startswith("suggest:")
    assert _counts(env) == before and env.woke == []
    assert _db(env, lambda c: tuple(c.execute("SELECT state, company_id, kind FROM swarm_suggestions").fetchone())) == ("pending", env.acme["id"], "project")

    _decide(env, ref, "approve")
    path = env.root / "Billing API"
    assert path.is_dir() and _is_repo_root(path)
    project = _db(env, lambda c: dict(c.execute("SELECT * FROM projects WHERE display_name = 'Billing API'").fetchone()))
    assert project["company_id"] == env.acme["id"] and os.path.realpath(project["root"]) == os.path.realpath(path)
    agent = _db(env, lambda c: store.get_project_agent(c, project["id"]))
    assert agent["rank"] == "project" and env.woke == [(agent["id"], "spawn")]
    assert _suggestion_state(env) == "approved"

    after = _counts(env)
    _decide(env, ref, "approve")
    _decide(env, ref, "decline")
    assert _counts(env) == after and len(env.woke) == 1 and _suggestion_state(env) == "approved"


def test_a_declined_card_writes_nothing(env):
    before = _counts(env)
    _suggest(env, "acmeboss", kind="project", name="Side Quest", reason="maybe")
    ref = env.port.cards[-1][2]
    _decide(env, ref, "decline")
    assert _counts(env) == before and env.woke == [] and _suggestion_state(env) == "declined"
    _decide(env, ref, "approve")
    assert _counts(env) == before and env.woke == [] and _suggestion_state(env) == "declined"


def test_rank_rule_and_name_rules(env):
    for slug, args in (("proj", dict(kind="project", name="X", reason="r")), ("proj", dict(kind="company", name="X", reason="r")),
                       ("acmeboss", dict(kind="company", name="X", reason="r")), ("alpha", dict(kind="project", name="X", reason="r"))):
        with pytest.raises(ToolError, match="only|asks its parent"):
            _suggest(env, slug, **args)
    for bad in ("../escape", ".hidden", "a/b", "x..y", "", "n" * 101):
        with pytest.raises(ToolError, match="name"):
            _suggest(env, "acmeboss", kind="project", name=bad, reason="r")
    with pytest.raises(ToolError, match="own company"):
        _suggest(env, "acmeboss", kind="project", name="Ok", reason="r", company_id=env.acme["id"] + 1)
    assert _db(env, lambda c: c.execute("SELECT COUNT(*) FROM swarm_suggestions").fetchone()[0]) == 0 and env.port.cards == []
    key = "AKIA" + "QWERTYUIOPASDFGH"
    _suggest(env, "acmeboss", kind="project", name="Starred", reason=f"deploy with {key} please")
    assert key not in _db(env, lambda c: c.execute("SELECT reason FROM swarm_suggestions").fetchone()[0])
    with pytest.raises(ToolError, match="already waiting"):
        _suggest(env, "acmeboss", kind="project", name="starred", reason="again")


def test_company_approval_makes_company_hq_repo_project_and_agent(env):
    before = _counts(env)
    _suggest(env, "alpha", kind="company", name="Zed Corp", reason="a new client")
    assert _counts(env) == before
    _decide(env, env.port.cards[-1][2], "approve")
    hq = env.root / "Zed Corp HQ"
    assert hq.is_dir() and _is_repo_root(hq)
    zed = next(c for c in _db(env, companies.list_companies) if c["name"] == "Zed Corp")
    project = _db(env, lambda c: dict(c.execute("SELECT * FROM projects WHERE company_id = ?", (zed["id"],)).fetchone()))
    assert project["display_name"] == "Zed Corp HQ" and os.path.realpath(project["root"]) == os.path.realpath(hq)
    assert _db(env, lambda c: c.execute("SELECT hq_project_id FROM companies WHERE id = ?", (zed["id"],)).fetchone()[0]) == project["id"]
    agent = _db(env, lambda c: dict(c.execute("SELECT * FROM swarm_agents WHERE company_id = ?", (zed["id"],)).fetchone()))
    assert agent["rank"] == "company" and agent["thread_key"] == f"agent:{agent['id']}" and agent["effort"] == "high"
    assert agent["project_id"] == project["id"] and profiles.effective_profile(agent) == profiles.SWARM_UPPER_ID
    assert env.woke == [(agent["id"], "spawn")]
    _db(env, lambda c: store.cas_state(c, agent["id"], "asleep", "awake"))
    with pytest.raises(project_agent.TurnOnError, match="already has an agent"):
        asyncio.run(company_agent.turn_on(SimpleNamespace(), zed["id"]))


def test_existing_hq_folder_is_refused_and_untouched(env):
    other = _db(env, lambda c: companies.create_company(c, "Taken"))
    (env.root / "Taken HQ").mkdir()
    (env.root / "Taken HQ" / "mine.txt").write_text("keep")
    before = _counts(env)
    with pytest.raises(project_agent.TurnOnError, match="already exists"):
        asyncio.run(company_agent.turn_on(SimpleNamespace(), other["id"]))
    assert _counts(env) == before and (env.root / "Taken HQ" / "mine.txt").read_text() == "keep" and not (env.root / "Taken HQ" / ".git").exists()
    with pytest.raises(project_agent.TurnOnError, match="already has an agent"):
        asyncio.run(company_agent.turn_on(SimpleNamespace(), env.acme["id"]))
    (env.root / "Blocked HQ").mkdir()
    with pytest.raises(ToolError, match="already exists"):
        _suggest(env, "alpha", kind="company", name="Blocked", reason="x")
    with pytest.raises(company_agent.CompanyMissing):
        asyncio.run(company_agent.turn_on(SimpleNamespace(), 999))


def test_company_turn_on_retries_a_wake_that_never_made_a_body(env):
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        other = companies.create_company(conn, "Retry Inc")
    agent = asyncio.run(company_agent.turn_on(SimpleNamespace(), other["id"]))
    assert agent["session_row_id"] is None
    again = asyncio.run(company_agent.turn_on(SimpleNamespace(), other["id"]))
    assert again["id"] == agent["id"] and env.woke == [(agent["id"], "spawn")] * 2


def test_accounts_are_pointers_and_a_secret_is_refused_naming_the_field(env):
    assert _db(env, lambda c: accounts.get_accounts(c, env.acme["id"])) == {}
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        assert accounts.set_accounts(conn, env.acme["id"], {"github": " acme-org ", "aws": "123456789012", "gcp": ""}) == {
            "github": "acme-org", "aws": "123456789012"}
        secret = "AKIA" + "QWERTYUIOPASDFGH"
        with pytest.raises(accounts.AccountsInvalid) as err:
            accounts.set_accounts(conn, env.acme["id"], {"aws": secret})
        assert "aws" in str(err.value) and secret not in str(err.value)
        with pytest.raises(accounts.AccountsInvalid, match="unknown"):
            accounts.set_accounts(conn, env.acme["id"], {"password": "x"})
        with pytest.raises(companies.CompanyNotFound):
            accounts.set_accounts(conn, 999, {})
        assert accounts.get_accounts(conn, env.acme["id"]) == {"github": "acme-org", "aws": "123456789012"}


def test_company_desk_lists_projects_pointers_and_suggestions(env):
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        accounts.set_accounts(conn, env.acme["id"], {"gcp": "acme-prod"})
    _suggest(env, "acmeboss", kind="project", name="Later", reason="r")
    boss = env.agents["acmeboss"]
    text = wake_prompt.render_desk(boss, "owner_message", "", _db(env, lambda c: desk.gather(c, boss)))
    assert "gcp acme-prod" in text and "agent:<id>" in text
    assert "\n  | Later\n" in text.partition(desk.DATA_HEADING)[2] and "Later" not in text.partition(desk.DATA_HEADING)[0]
    assert desk.render(_db(env, lambda c: desk.gather(c, env.agents["proj"]))) == ["- nothing open"]


def test_v65_adds_the_columns_and_the_table(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        with conn:
            run_chain(conn, 0, 64)
        assert "accounts" not in {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
        with conn:
            run_chain(conn, 64, 65)
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(companies)")}
        assert cols["accounts"][4] == "'{}'" and "hq_project_id" in cols
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'swarm_suggestions'").fetchone()
