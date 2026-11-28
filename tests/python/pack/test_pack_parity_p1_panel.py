
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.api import federation_pack_global_routes as routes
from src.core.computers import direction
from src.core.db import connect, db_path_for, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import META_INSTALL_ID
from src.core.federation import fed_key, grants, peer_hosts, peer_token
from src.core.pack.globalsync import panel, panel_apply, sender
from src.core.pack.globalsync.sender import GlobalSync, PANEL_CAP, PeerView
from src.core.pack.globalsync.store import Status
from src.core.pack.machines import capabilities as caps, config_state, restrictions
from src.core.pack.meshdata import gossip, panel_kind
from tests.python.pack.test_mesh_panel import Mesh, uid


def test_pack_ui_restriction_defaults_decoupled_from_global_setup() -> None:
    default = restrictions.Restrictions()
    assert default.may_receive_pack_ui is True
    assert default.may_receive_global_setup is False
    assert "pack-ui" in restrictions.MANAGED_SCOPES
    assert "pack-ui" in grants.KNOWN_SCOPES
    scopes = restrictions.scopes_for(default, tracks_master=False)
    assert "pack-ui" in scopes and "global-setup" not in scopes
    assert restrictions.check(default, restrictions.ACTION_RECEIVE_PACK_UI) is None
    assert restrictions.check(default, restrictions.ACTION_RECEIVE_GLOBAL_SETUP) == "may_receive_global_setup"

    locked = restrictions.Restrictions(may_receive_pack_ui=False)
    assert "pack-ui" not in restrictions.scopes_for(locked, tracks_master=False)
    assert restrictions.check(locked, restrictions.ACTION_RECEIVE_PACK_UI) == "may_receive_pack_ui"
    assert restrictions.narrows(default, locked) is True
    assert restrictions.narrows(locked, default) is False


def test_legacy_panel_http_route_uses_pack_ui_not_global_setup(tmp_path: Path, monkeypatch: Any) -> None:
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    recv_iid, main_iid = "iid-recv", "iid-main"
    with closing(connect(db_path_for(state), create=False)) as conn:
        set_meta(conn, META_INSTALL_ID, recv_iid)
        key = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([7]) * 32))
        grant = grants.create_grant(conn, peer_install_id=main_iid, public_key=key, label="main", scopes=("pack-ui",))
    token = peer_token.mint(grant, recv_iid)[0]

    pack_ui_on = {"v": True}
    monkeypatch.setattr(routes, "state_dir", lambda: state)
    monkeypatch.setattr(routes, "open_db", lambda: connect(db_path_for(state), create=False))
    monkeypatch.setattr(routes, "content_alpha", lambda: main_iid)
    monkeypatch.setattr(routes, "_panel_on", lambda: True)
    monkeypatch.setattr(routes.direction, "contained", lambda _peer: False)
    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(
        restrictions=lambda: restrictions.Restrictions(may_receive_global_setup=False, may_receive_pack_ui=pack_ui_on["v"])
    ))
    from src.api import peer_auth
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(db_path_for(state), create=False))

    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    doc = {"v": 1, "companies": [{"uid": uid(1), "name": "Nyedis", "parent_uid": None, "hue": 200, "gone": False}],
           "projects": [], "groups": [], "arrangement": {"pinned": [], "order": [], "bands": {}, "sections": None}}

    ok = client.post(f"/api/v1{sender.PANEL_PATH}", headers=headers, json={"doc": doc})
    assert ok.status_code == 200, ok.text
    assert ok.json()["report"]["companies_created"] == 1

    pack_ui_on["v"] = False
    refused = client.post(f"/api/v1{sender.PANEL_PATH}", headers=headers, json={"doc": doc})
    assert refused.status_code == 403 and refused.json()["detail"]["rule"] == "may_receive_pack_ui"


def test_legacy_sender_delivers_panel_without_global_setup_opt_in_or_account_approval(tmp_path: Path) -> None:
    calls: List[str] = []

    def req_for(_iid: str, _timeout: float) -> Any:
        async def request(_method: str, path: str, json: Any = None) -> tuple:
            calls.append(path)
            return 200, {"report": {}}
        return request

    view = PeerView("iid-b", "b", True, [PANEL_CAP])
    panel_allow = {"v": True}
    box = GlobalSync(
        settings=lambda: {"enabled": False, "auto": False, "claude": True, "codex": True, "panel": True},
        is_main=lambda: True, peers=lambda: [view], approved=lambda _i: False, allows=lambda _i: False,
        panel_allows=lambda _i: panel_allow["v"], contained=lambda _i: False, accounts=lambda: [],
        request_for=req_for, status=Status(tmp_path / "s.json"), outbox=tmp_path / "out", home=tmp_path,
        notify=lambda: None, panel_doc=lambda: {"v": 1}, panel_status=Status(tmp_path / "p.json"),
    )
    assert asyncio.run(box.sync(files=False, force=True)) == {"iid-b": "synced"}
    assert calls == [sender.PANEL_PATH]

    panel_allow["v"] = False
    assert asyncio.run(box.sync(files=False, force=True)) == {"iid-b": sender.RECEIVER_OFF}
    assert len(calls) == 1


@pytest.fixture()
def mesh_factory(tmp_path: Path, monkeypatch: Any) -> Any:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    monkeypatch.setattr(gossip, "STEPS", [])
    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(
        restrictions=lambda: restrictions.Restrictions(may_receive_global_setup=False, may_receive_pack_ui=True)
    ))

    async def quiet(_state: Any, _report: Any, _result: Any) -> bool:
        return False

    monkeypatch.setattr(panel_apply, "announce", quiet)
    return lambda *names, **kw: Mesh(tmp_path, *names, **kw)


def test_non_one_way_member_without_may_receive_logins_syncs_and_applies_panel(mesh_factory: Any) -> None:
    m = mesh_factory("a", "b", no_yes={"b"})
    a, b = m["a"], m["b"]
    a.project("AlphaProj", uid(1))
    b.project("OldName", uid(1))
    assert panel_kind.approved_listed(m.lst(), b.iid) is True
    m.seed_all()
    a.sql("UPDATE projects SET display_name = 'SyncedName', color = '#8a1c00' WHERE uid = ?", uid(1))
    a.step()
    m.converge(("a", "b"))
    b.step()
    assert b.project_name(uid(1)) == "SyncedName"


def test_stale_digest_fix_applies_already_held_records_to_newly_minted_shadow_project(mesh_factory: Any) -> None:
    m = mesh_factory("a", "b")
    a, b = m["a"], m["b"]
    puid, cuid = uid(42), uid(7)
    a.sql("INSERT INTO companies (name, uid, created_at, updated_at) VALUES ('Nyedis', ?, 't', 't')", cuid)
    m.seed_all()
    assert m.stores["a"].put_many(
        "panel",
        [(f"p:{puid}:name", "Carnivore.ai", None), (f"p:{puid}:color", "#8a1c00", None), (f"p:{puid}:company_uid", cuid, None)],
        m.signing["a"], m.lst(),
    ) == (3, 0)
    m.converge(("a", "b"))
    b.step()
    assert b.project_name(puid) is None
    digest_before = m.stores["b"].kind_digest(m.lst(), "panel")

    with closing(b.db()) as conn:
        conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, presence, host_key, created_at, updated_at, last_opened_at, uid) "
            "VALUES (?, ?, 'cloudecode', 'user', 'unchecked', 'peer-abc', 't', 't', 't', ?)",
            ("peer://peer-abc/Users/a/cloudecode", "peer://peer-abc/Users/a/cloudecode", puid),
        )
        conn.commit()
    assert m.stores["b"].kind_digest(m.lst(), "panel") == digest_before

    b.step()
    with closing(b.db()) as conn:
        row = conn.execute(
            "SELECT p.display_name, p.color, c.name AS cname FROM projects p "
            "LEFT JOIN companies c ON c.id = p.company_id WHERE p.uid = ?",
            (puid,),
        ).fetchone()
    assert tuple(row) == ("Carnivore.ai", "#8a1c00", "Nyedis")


def test_company_deletion_tombstone_propagates_and_survives_gc(mesh_factory: Any) -> None:
    m = mesh_factory("a", "b")
    a, b = m["a"], m["b"]
    parent_uid, child_uid, puid = uid(10), uid(11), uid(12)
    with closing(a.db()) as conn:
        pid_c = conn.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES ('ParentCo', ?, 't', 't')", (parent_uid,)).lastrowid
        conn.execute("INSERT INTO companies (name, uid, parent_id, created_at, updated_at) VALUES ('ChildCo', ?, ?, 't', 't')", (child_uid, pid_c))
        conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, presence, company_id, created_at, updated_at, last_opened_at, uid) "
            "VALUES ('/r/p', '/r/p', 'Proj', 'user', 'present', ?, 't', 't', 't', ?)",
            (pid_c, puid),
        )
        conn.commit()
    m.seed_all()
    m.converge(("a", "b"))
    b.step()
    with closing(b.db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 2
        assert conn.execute("SELECT c.uid FROM projects p JOIN companies c ON c.id = p.company_id WHERE p.uid = ?", (puid,)).fetchone()[0] == parent_uid

    with closing(a.db()) as conn:
        cid = conn.execute("SELECT id FROM companies WHERE uid = ?", (parent_uid,)).fetchone()[0]
        conn.execute("UPDATE projects SET company_id = NULL WHERE company_id = ?", (cid,))
        conn.execute("UPDATE companies SET parent_id = NULL WHERE parent_id = ?", (cid,))
        conn.execute("DELETE FROM companies WHERE id = ?", (cid,))
        conn.commit()
    m.now += 1000
    a.step()
    assert a.rows()[f"c:{parent_uid}:gone"][0] is True
    assert panel_kind.is_tomb(True) is False

    m.converge(("a", "b"))
    b.step()
    with closing(b.db()) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM companies ORDER BY name")]
        child_parent = conn.execute("SELECT parent_id FROM companies WHERE uid = ?", (child_uid,)).fetchone()[0]
        proj_co = conn.execute("SELECT company_id FROM projects WHERE uid = ?", (puid,)).fetchone()[0]
    assert names == ["ChildCo"] and child_parent is None and proj_co is None

    m.now += panel_kind.TOMB_TTL_MS + 10_000
    assert m.stores["b"].gc(m.now) == 0
    assert b.rows()[f"c:{parent_uid}:gone"][0] is True


def test_project_archived_parent_uid_and_sessionless_stub_materialization(mesh_factory: Any) -> None:
    m = mesh_factory("a", "b")
    a, b = m["a"], m["b"]
    parent_uid, child_uid, co_uid = uid(20), uid(21), uid(22)
    with closing(b.db()) as conn:
        host = peer_hosts.upsert(conn, install_id=a.iid, label="alpha", grant_id="g-a", fid="f-a", initiator=True)
        expected_host_key = host.key
    with closing(a.db()) as conn:
        co_id = conn.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES ('Acme', ?, 't', 't')", (co_uid,)).lastrowid
        conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, presence, company_id, color, short_description, created_at, updated_at, last_opened_at, uid) "
            "VALUES ('/Users/demo/secret/parent', '/Users/demo/secret/parent', 'ParentProj', 'user', 'present', ?, '#112233', 'Parent desc', 't', 't', 't', ?)",
            (co_id, parent_uid),
        )
        conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, presence, company_id, color, archived_at, created_at, updated_at, last_opened_at, uid) "
            "VALUES ('/Users/demo/secret/parent/child', '/Users/demo/secret/parent/child', 'ChildProj', 'user', 'present', ?, '#445566', '2026-11-26T00:00:00Z', 't', 't', 't', ?)",
            (co_id, child_uid),
        )
        conn.commit()

    m.seed_all()
    m.converge(("a", "b"))
    b.step()
    b.step()
    assert b.own_rows() == []

    with closing(b.db()) as conn:
        parent_row = conn.execute("SELECT root, raw_path, display_name, host_key, home_install_id, color, short_description, archived_at, presence FROM projects WHERE uid = ?", (parent_uid,)).fetchone()
        child_row = conn.execute("SELECT root, raw_path, display_name, host_key, home_install_id, color, archived_at, presence FROM projects WHERE uid = ?", (child_uid,)).fetchone()
        synced_parents = panel.synced_project_parents(conn)

    assert parent_row is not None and child_row is not None
    assert parent_row["root"] == f"peer://{a.iid}/{parent_uid}"
    assert parent_row["raw_path"] == f"peer://{a.iid}/{parent_uid}"
    assert "/Users/demo/secret" not in parent_row["root"] and "/Users/demo/secret" not in child_row["root"]
    assert (parent_row["display_name"], parent_row["host_key"], parent_row["home_install_id"], parent_row["color"], parent_row["short_description"], parent_row["archived_at"], parent_row["presence"]) == (
        "ParentProj", expected_host_key, a.iid, "#112233", "Parent desc", None, "unchecked"
    )
    assert child_row["root"] == f"peer://{a.iid}/{child_uid}"
    assert child_row["display_name"] == "ChildProj" and child_row["archived_at"] is not None and child_row["presence"] == "unchecked"
    assert synced_parents == {child_uid: parent_uid}

    a.sql("UPDATE projects SET archived_at = NULL WHERE uid = ?", child_uid)
    m.now += 1000
    a.step()
    m.converge(("a", "b"))
    b.step()
    with closing(b.db()) as conn:
        assert conn.execute("SELECT archived_at FROM projects WHERE uid = ?", (child_uid,)).fetchone()[0] is None
