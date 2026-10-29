
from __future__ import annotations

import io
import json
import os
import tempfile
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_s8a_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_s8a_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import swarm_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.companies import accounts as company_accounts, store as company_store
from src.core.swarm import body_create, definition, export, fact_index, memory, store, thread_port

SECRET = "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bD1fH3jL5"
GOAL = "swap the checkout model for the vendor demo"


class Port:
    pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    assert ensure_db_migrated(state).status == "ok"
    thread_port.register(Port())
    conn = connect(db_path_for(state))
    repo = tmp_path / "acmeshop"
    repo.mkdir()
    parent = store.create_agent(conn, slug="odin", rank="project", job="repo", display_name="Odin Prime", effort="high",
                                repo_dir=str(repo))
    agent = store.create_agent(conn, slug="loki-swap", rank="feature", job="swap models", display_name="Loki (Swap)",
                               effort="medium", repo_dir=str(repo), parent_id=parent["id"], goal=GOAL, persona="a careful tinker")
    body_create.write_files(state, agent, "Odin Prime")
    mem = memory.memory_dir(repo, "loki-swap", "project")
    app = FastAPI()
    app.include_router(swarm_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    yield SimpleNamespace(state=state, conn=conn, agent=agent, repo=repo, mem=mem, app=app)
    thread_port.register(None)
    conn.close()


def add_fact(env, fid, title, text, scope="craft", state="live") -> None:
    f = memory.Fact(f"f_{fid:012x}", title, scope, "agent", "2026-10-05T10:00:00Z", text)
    memory.atomic_write(env.mem / "facts" / f"{f.id}.md", memory.render_fact(f))
    env.conn.execute("INSERT INTO swarm_facts (id, agent_id, rel_path, title, scope, origin, taught_at, sha256, state) "
                     "VALUES (?, ?, ?, ?, ?, 'agent', ?, 'x', ?)",
                     (f.id, env.agent["id"], f"facts/{f.id}.md", title, scope, f.taught_at, state))
    env.conn.commit()


def names(data: bytes) -> list:
    return zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_only_craft_facts_ship_and_the_definition_is_stripped(env):
    add_fact(env, 1, "use the model command", "restart the session after swapping models")
    add_fact(env, 2, "checkout uses acme vendor", f"the repo lives at {env.repo}/src and the vendor is acme", scope="project")
    add_fact(env, 3, "held craft fact", "never shipped while held", state="held")
    memory.atomic_write(env.mem / "facts" / "hand-note.md", "a note with no row")
    data = export.build_blocking(env.conn, env.agent)
    z = zipfile.ZipFile(io.BytesIO(data))
    got = z.namelist()
    assert got == ["README.md", ".claude/agents/loki-swap.md", ".codex/agents/loki-swap.toml",
                   ".claude/agent-memory/loki-swap/MEMORY.md", f".claude/agent-memory/loki-swap/facts/f_{1:012x}.md"]
    assert all(not n.startswith("/") and ".." not in n for n in got)
    fact = memory.parse_fact(z.read(got[-1]).decode())
    assert (fact.title, fact.origin, fact.owner_message_ref) == ("use the model command", "agent", None)
    index = z.read(got[3]).decode()
    assert f"f_{1:012x}" in index and f"f_{2:012x}" not in index and "hand-note" not in index
    blob = "\n".join(z.read(n).decode() for n in got)
    for leaked in (GOAL, "Your order", "Origin message", "Odin Prime", str(env.repo), "acmeshop", "acme vendor", "swarm_say", "swarm.json"):
        assert leaked not in blob
    parsed = definition.parse_definition(z.read(got[1]).decode())
    assert parsed.memory == "project" and "## 1. Who you are" in parsed.brief and "## 5. The rules that bind you" in parsed.brief
    assert "## 6. How to report" in parsed.brief and ".claude/agent-memory/loki-swap/MEMORY.md" in parsed.brief
    twin = tomllib.loads(z.read(got[2]).decode())
    assert ".claude/agent-memory/loki-swap/MEMORY.md" in twin["developer_instructions"]


def test_route_returns_zip_and_refuses_a_secret_without_echoing_it(env, caplog):
    add_fact(env, 1, "use the model command", "restart the session after swapping models")
    add_fact(env, 2, "project note with a key", f"the key is {SECRET}", scope="project")

    async def get(path):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t") as c:
            return await c.get(path)

    import asyncio

    ok = asyncio.run(get(f"/swarm/agents/{env.agent['id']}/export"))
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/zip"
    assert "attachment" in ok.headers["content-disposition"] and SECRET.encode() not in ok.content
    add_fact(env, 4, "craft note with a key", f"the key is {SECRET}")
    with caplog.at_level("DEBUG"):
        bad = asyncio.run(get(f"/swarm/agents/{env.agent['id']}/export"))
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "secret_found"
    assert f"f_{4:012x}.md" in bad.json()["detail"]["message"]
    assert SECRET not in bad.text and SECRET not in caplog.text
    assert asyncio.run(get("/swarm/agents/9999/export")).status_code == 404


def test_handwritten_row_never_ships_even_when_its_file_claims_craft(env):
    fid = "f_0000000000aa"
    note = memory.Fact(fid, "dropped in by hand", "craft", "agent", "2026-10-05T10:00:00Z", "pretend this was vouched for")
    memory.atomic_write(env.mem / "facts" / f"{fid}.md", memory.render_fact(note))
    fact_index._register_handwritten(env.conn, env.agent["id"], env.mem)
    row = env.conn.execute("SELECT origin, scope, state FROM swarm_facts WHERE id = ?", (fid,)).fetchone()
    assert tuple(row) == ("handwritten", "craft", "live")
    z = zipfile.ZipFile(io.BytesIO(export.build_blocking(env.conn, env.agent)))
    assert not any(fid in n for n in z.namelist())
    assert fid not in z.read(".claude/agent-memory/loki-swap/MEMORY.md").decode()


def test_home_names_pointers_paths_and_emails_never_ship(env):
    company = company_store.create_company(env.conn, "Globex Corp")
    pointers = {"github": "globex-inc", "aws": "123456789012", "gcp": "globex-prod"}
    company_accounts.set_accounts(env.conn, company["id"], pointers)
    hq = env.repo.parent / "Globex Corp HQ"
    hq.mkdir()
    agent = store.create_agent(env.conn, slug="hela", rank="feature", job="company agent for Globex Corp", display_name="Hela",
                               effort="medium", repo_dir=str(hq), parent_id=env.agent["id"], goal=GOAL, company_id=company["id"], persona="Zeus")
    body_create.write_files(env.state, agent, "Loki (Swap)")
    mem = memory.memory_dir(hq, "hela", "project")
    text = ("Globex Corp HQ deploys to AWS account 123456789012 under github globex-inc and gcp globex-prod; "
            "mail ops@globex.example; see file:///Users/Alex/secret/notes and Edit(//Users/Alex/x/**) and src/Users/x; "
            "icloud /Users/alex/Library/Mobile Documents/com~apple~CloudDocs/Development/Sibling Proj/a.py ok; "
            "home ~/Library/Application Support/Sibling Proj/x ok; clone git@github.com:globexorg/zorbapp.git and "
            "https://github.com/globexorg/zorbapp; "
            f"folder {env.repo.parent}/Quux Wibble Wobble/a.py and {Path.home()}/Development/Quux Wibble Wobble/b.py ok; "
            "mirrors https://gitlab.example.net/quuxorg/quuxrepo.git and git@bitbucket.example.org:quuxorg/quuxrepo.git and "
            "ssh://git@git.example.net/quuxorg/quuxrepo; spelled GlobexCorp, globex_corp and globex-corp; persona Zeus")
    fact = memory.Fact("f_0000000000bb", "Globex Corp HQ habit", "craft", "agent", "2026-10-05T10:00:00Z", text)
    memory.atomic_write(mem / "facts" / f"{fact.id}.md", memory.render_fact(fact))
    env.conn.execute("INSERT INTO swarm_facts (id, agent_id, rel_path, title, scope, origin, taught_at, sha256, state) "
                     "VALUES (?, ?, ?, ?, 'craft', 'agent', ?, 'x', 'live')",
                     (fact.id, agent["id"], f"facts/{fact.id}.md", fact.title, fact.taught_at))
    env.conn.commit()
    z = zipfile.ZipFile(io.BytesIO(export.build_blocking(env.conn, agent)))
    assert f".claude/agent-memory/hela/facts/{fact.id}.md" in z.namelist()
    blob = "\n".join(z.read(n).decode() for n in z.namelist()).lower()
    for leaked in ("globex", "123456789012", "ops@", "/users/alex", "//users"):
        assert leaked not in blob
    for leaked in ("sibling proj", "clouddocs", "application support", "zorbapp", "globexorg", "zeus",
                   "wibble", "wobble", "quux", "gitlab", "bitbucket"):
        assert leaked not in blob
    assert "src/Users/x".lower() in blob
