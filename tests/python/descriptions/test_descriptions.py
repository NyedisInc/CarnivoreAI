
from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.python.companies.conftest import client, world  # noqa: F401
from src.core import db_schema_audit
from src.core.companies import store as companies
from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.descriptions import roster, store
from src.core.descriptions.ddl import apply_v74
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402

U_LIVE, U_NAP, U_GONE, U_SHELF = (f"{c * 8}-1111-4111-8111-111111111111" for c in "abcd")


def _columns(conn, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _session(conn, uuid, name, project_id, *, lifecycle="running", source=None, archived_at=None, epoch=1000):
    conn.execute(
        "INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, tmux_created_epoch, lifecycle, "
        "lifecycle_source, archived_at, project_id, agent_type, title, created_at, updated_at) "
        "VALUES (?, 'created', 'cloude', ?, ?, ?, ?, ?, ?, 'claude', ?, 'x', 'x')",
        (uuid, name, epoch, lifecycle, source, archived_at, project_id, name))
    return conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()[0]


def test_fresh_database_has_the_three_columns_and_the_audit_declares_them(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        with conn:
            run_chain(conn, 0, CURRENT_SCHEMA_VERSION)
        assert CURRENT_SCHEMA_VERSION >= 74
        assert "short_description" in _columns(conn, "projects") and "description" in _columns(conn, "projects")
        assert {"short_description", "long_description"} <= _columns(conn, "sessions")
        assert db_schema_audit.audit_schema(conn, CURRENT_SCHEMA_VERSION).status == db_schema_audit.AUDIT_OK
    names = {o.name for o in db_schema_audit.declared_objects(CURRENT_SCHEMA_VERSION)}
    assert {"projects.short_description", "sessions.short_description", "sessions.long_description"} <= names


def test_v73_upgrade_adds_columns_and_keeps_every_existing_value(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        with conn:
            run_chain(conn, 0, 73)
        conn.execute("INSERT INTO projects (root, raw_path, display_name, description, source, created_at, updated_at) "
                     "VALUES ('/p', '/p', 'p', 'the old long text', 'user', 'x', 'x')")
        _session(conn, U_LIVE, "cloude_a", 1)
        conn.commit()
        assert "short_description" not in _columns(conn, "projects")
        with conn:
            run_chain(conn, 73, 74)
        apply_v74(conn)
        assert tuple(conn.execute("SELECT description, short_description FROM projects").fetchone()) == ("the old long text", None)
        assert tuple(conn.execute("SELECT title, short_description, long_description FROM sessions").fetchone()) == (
            "cloude_a", None, None)


def test_project_route_caps_and_round_trips_both_descriptions(client, world):  # noqa: F811
    base = "/api/v1/projects/alpha"
    assert client.patch(base, json={"short_description": "x" * 121}).status_code == 422
    assert client.patch(base, json={"description": "x" * 2001}).status_code == 422
    assert client.patch(base, json={"short_description": "two\nlines"}).status_code == 400
    ok = client.patch(base, json={"short_description": "x" * 120, "description": "y" * 2000})
    assert ok.status_code == 200, ok.text
    assert ok.json()["short_description"] == "x" * 120 and ok.json()["description"] == "y" * 2000
    listed = {p["name"]: p for p in client.get("/api/v1/projects").json()}
    assert listed["alpha"]["short_description"] == "x" * 120
    assert client.patch(base, json={"short_description": ""}).json()["short_description"] is None


def test_session_route_caps_writes_and_feeds_the_listing_index(client, world):  # noqa: F811
    with closing(connect(world.db)) as conn:
        row_id = _session(conn, U_LIVE, "cloude_a", world.ids["alpha"])
        conn.commit()
    store.reset_index()
    url = f"/api/v1/sessions/records/{U_LIVE}/description"
    assert client.patch(url, json={"short_description": "x" * 121}).status_code == 422
    assert client.patch(url, json={"long_description": "x" * 2001}).status_code == 422
    assert client.patch(url, json={"short_description": "a\nb"}).status_code == 400
    assert client.patch(url, json={}).status_code == 400
    assert client.patch(f"/api/v1/sessions/records/{U_GONE}/description", json={"short_description": "x"}).status_code == 404
    ok = client.patch(url, json={"short_description": "  ships the release ", "long_description": "x" * 2000})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"session_uuid": U_LIVE, "session_row_id": row_id, "short_description": "ships the release",
                         "long_description": "x" * 2000}
    assert store.short_for_row(row_id, world.state_dir) == "ships the release"
    store.reset_index()
    assert store.short_for_row(row_id, world.state_dir) == "ships the release"


def _live(row_id, name, project_id, status="working"):
    return SimpleNamespace(session_row_id=row_id, tmux_session=name, label=None, project_id=project_id,
                           activity_status=status, agent_type="claude", host_key="local",
                           host_label="here", session=SimpleNamespace(id=f"ses_{name}", working_dir="/w", tmux_created_epoch=1000))


@pytest.fixture()
def family(world):  # noqa: F811
    with closing(connect(world.db)) as conn:
        imc = companies.create_company(conn, "IMC")["id"]
        ami = companies.create_company(conn, "Amerifund", parent_id=imc)["id"]
        companies.assign_project(conn, world.ids["alpha"], ami)
        conn.execute("UPDATE projects SET short_description = 'the loan app' WHERE id = ?", (world.ids["alpha"],))
        conn.execute("UPDATE projects SET archived_at = 'x' WHERE id = ?", (world.ids["beta"],))
        live = _session(conn, U_LIVE, "cloude_a", world.ids["alpha"])
        _session(conn, U_NAP, "cloude_nap", world.ids["alpha"], lifecycle="stopped", source="slept_by_user")
        _session(conn, U_GONE, "cloude_gone", world.ids["alpha"], lifecycle="stopped", archived_at="x")
        _session(conn, U_SHELF, "cloude_shelf", world.ids["beta"], lifecycle="stopped", source="tmux_missing")
        conn.execute("UPDATE sessions SET short_description = 'ships', long_description = 'ships the release' "
                     "WHERE session_uuid = ?", (U_LIVE,))
        conn.execute("UPDATE sessions SET short_description = 'naps' WHERE session_uuid = ?", (U_NAP,))
        conn.commit()
        ctx = roster.read_context(conn)
    return SimpleNamespace(ctx=ctx, infos=[_live(live, "cloude_a", world.ids["alpha"])], imc=imc, ami=ami,
                           world=world)


def _names(answer) -> list:
    return sorted(e["tmux_name"] for e in answer["sessions"])


def test_roster_scopes_mark_archived_and_keep_the_payload_lean(family):
    online = roster.build_roster(family.ctx, family.infos)
    assert _names(online) == ["cloude_a"]
    entry = online["sessions"][0]
    assert (entry["id"], entry["status"], entry["live"], entry["archived"]) == ("ses_cloude_a", "working", True, False)
    assert entry["short_description"] == "ships" and "long_description" not in entry
    assert _names(roster.build_roster(family.ctx, family.infos, scope="around")) == ["cloude_a", "cloude_nap"]
    every = roster.build_roster(family.ctx, family.infos, scope="all", detail=True)
    assert _names(every) == ["cloude_a", "cloude_gone", "cloude_nap", "cloude_shelf"]
    by = {e["tmux_name"]: e for e in every["sessions"]}
    assert by["cloude_gone"]["archived"] is True and by["cloude_gone"]["archived_by"] == "session"
    assert by["cloude_shelf"]["archived_by"] == "project" and by["cloude_shelf"]["status"] == "archived"
    assert "wake_hint" in by["cloude_gone"] and "deliberate" in every["note"]
    assert by["cloude_nap"]["asleep"] is True and by["cloude_nap"]["status"] == "asleep"
    assert by["cloude_a"]["long_description"] == "ships the release"
    with pytest.raises(roster.RosterRefused):
        roster.build_roster(family.ctx, family.infos, scope="everyone")


def test_roster_family_lineage_and_filters(family):
    every = {e["tmux_name"]: e for e in roster.build_roster(family.ctx, family.infos, scope="all")["sessions"]}
    fam = every["cloude_a"]["family"]
    assert fam["project"]["name"] == "alpha" and fam["project"]["short_description"] == "the loan app"
    assert fam["company"] == {"id": family.ami, "name": "Amerifund"}
    assert fam["parent_companies"] == [{"id": family.imc, "name": "IMC"}]
    run = lambda **kw: _names(roster.build_roster(family.ctx, family.infos, scope="all", **kw))  # noqa: E731
    assert run(has_description="short") == ["cloude_a", "cloude_nap"]
    assert run(has_description="long") == ["cloude_a"]
    assert run(has_description="none") == ["cloude_gone", "cloude_shelf"]
    assert run(has_description="missing") == ["cloude_gone", "cloude_nap", "cloude_shelf"]
    assert run(company="imc") == ["cloude_a", "cloude_gone", "cloude_nap"]
    assert run(company=str(family.ami)) == run(company="IMC")
    assert run(project="beta") == ["cloude_shelf"]


def test_roster_route_and_mcp_adapter(client, family, monkeypatch):  # noqa: F811
    from src.api import descriptions_routes
    from src.core.mcp import beast_mode, pending, session_target, tools
    from src.core.mcp.caller import AgentCaller

    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    arm_beast(monkeypatch, lambda: False)
    monkeypatch.setattr(session_target, "_session_uuid_of_row", lambda row_id: U_LIVE)

    class Manager:
        app = client.app

        async def list_session_infos(self):
            return family.infos

        async def list_peer_infos(self):
            return []

    client.app.state.session_manager = Manager()
    answer = client.get("/api/v1/sessions/roster", params={"scope": "around", "company": "IMC"}).json()
    assert _names(answer) == ["cloude_a", "cloude_nap"]
    assert client.get("/api/v1/sessions/roster", params={"has_description": "maybe"}).status_code == 400

    request = SimpleNamespace(app=client.app)
    direct = asyncio.run(descriptions_routes.get_roster(request, scope="all", has_description="any", project=None,
                                                        company=None, detail=False))
    assert direct["total"] == 4
    pane = AgentCaller("ses_cloude_a", "cloude_a", "ses_cloude_a")
    names = {d["name"] for d in tools.tool_definitions(AgentCaller("x", "x", "x", scope="read"))}
    assert "sessions_roster" in names and "session_description_set" not in names
    assert {"session_description_set", "project_description_set"} <= tools.WRITE_TOOLS
    assert "session_description_set" not in tools._UNGATED_WRITES
    import json

    via_mcp = asyncio.run(tools.call_tool(Manager(), pane, "sessions_roster", {"scope": "all", "company": family.imc}))
    assert not via_mcp.get("isError"), via_mcp
    body = json.loads(via_mcp["content"][0]["text"])
    assert _names(body) == ["cloude_a", "cloude_gone", "cloude_nap"] and "deliberate" in body["note"]
    held = asyncio.run(tools.call_tool(Manager(), pane, "session_description_set",
                                       {"target": "cloude_a", "short_description": "mine"}))
    assert "pending" in str(held)
    queue = pending.get_store()
    asyncio.run(queue.approve(queue.list()[0]["id"]))
    with closing(connect(family.world.db)) as conn:
        assert conn.execute("SELECT short_description FROM sessions WHERE session_uuid = ?", (U_LIVE,)).fetchone()[0] == "mine"


def test_listing_marker_stamps_the_wrapper_from_memory(world):  # noqa: F811
    from src.api.description_listing import mark_descriptions
    from src.models import SessionInfo

    with closing(connect(world.db)) as conn:
        row_id = _session(conn, U_LIVE, "cloude_a", world.ids["alpha"])
        store.set_session_descriptions(conn, U_LIVE, short_description="ships")
    info = SessionInfo.model_construct(host_key="local", origin_install_id=None, session_row_id=row_id,
                                       session=SimpleNamespace(id="ses_cloude_a"), short_description=None)
    mark_descriptions(None, [info])
    assert info.short_description == "ships"
