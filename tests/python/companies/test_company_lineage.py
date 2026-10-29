
from __future__ import annotations

from contextlib import closing

import pytest

from tests.python.companies.conftest import client, world  # noqa: F401
from src.core.companies import lineage, store
from src.core.db import connect
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.project_writes import create_project

BASE = "/api/v1/companies"


def test_v71_database_gains_parent_id_and_existing_companies_stay_top_level(tmp_path):
    from src.core.companies.ddl import apply_v72
    from src.core.db import db_path_for

    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 71)
        conn.execute("INSERT INTO companies (name, created_at, updated_at) VALUES ('Old', 'x', 'x')")
        assert "parent_id" not in {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
        assert store.list_companies(conn)[0]["parent_id"] is None
        with conn:
            run_chain(conn, 71, 72)
        apply_v72(conn)
        assert CURRENT_SCHEMA_VERSION >= 72
        assert conn.execute("SELECT parent_id FROM companies").fetchone()[0] is None


def test_lineage_rules_are_pure():
    parents = {1: None, 2: 1, 3: 2, 4: 3, 5: None, 6: 5}
    assert lineage.level_of(parents, 4) == 4 and lineage.subtree_height(parents, 1) == 4
    with pytest.raises(lineage.CompanyParentCycle):
        lineage.validate_parent(parents, 1, 3)
    with pytest.raises(lineage.CompanyParentCycle):
        lineage.validate_parent(parents, 2, 2)
    with pytest.raises(lineage.CompanyTooDeep):
        lineage.validate_parent(parents, None, 4)
    with pytest.raises(lineage.CompanyTooDeep):
        lineage.validate_parent(parents, 5, 3)
    lineage.validate_parent(parents, 5, 2)
    lineage.validate_parent(parents, None, 3)


def test_routes_create_nest_refuse_and_delete_moves_children_up(client):  # noqa: F811
    imc = client.post(BASE, json={"name": "IMC"}).json()
    assert imc["parent_id"] is None and imc["hq_project_id"] is None
    amf = client.post(BASE, json={"name": "Amerifund", "parent_id": imc["id"]}).json()
    assert amf["parent_id"] == imc["id"]
    sub = client.post(BASE, json={"name": "Support", "parent_id": amf["id"]}).json()
    assert client.post(BASE, json={"name": "Nope", "parent_id": 4242}).status_code == 404
    cycle = client.patch(f"{BASE}/{imc['id']}", json={"parent_id": sub["id"]})
    assert cycle.status_code == 409 and "cannot be its parent" in cycle.json()["detail"]
    deep = client.post(BASE, json={"name": "L4", "parent_id": sub["id"]}).json()
    too_deep = client.post(BASE, json={"name": "L5", "parent_id": deep["id"]})
    assert too_deep.status_code == 422 and "at most 4 levels" in too_deep.json()["detail"]
    assert client.patch(f"{BASE}/{amf['id']}", json={"parent_id": None}).json()["parent_id"] is None
    assert client.patch(f"{BASE}/{amf['id']}", json={"parent_id": imc["id"]}).status_code == 200
    gone = client.delete(f"{BASE}/{amf['id']}").json()
    assert gone == {"deleted": True, "orphaned": 0, "children_moved": 1}
    listed = {c["name"]: c for c in client.get(BASE).json()["companies"]}
    assert listed["Support"]["parent_id"] == imc["id"] and listed["L4"]["parent_id"] == sub["id"]
    gone = client.delete(f"{BASE}/{imc['id']}").json()
    assert gone["children_moved"] == 1
    assert {c["name"]: c["parent_id"] for c in client.get(BASE).json()["companies"]}["Support"] is None


def test_hq_project_is_set_cleared_and_validated(client, world):  # noqa: F811
    acme = client.post(BASE, json={"name": "Acme"}).json()
    set_ = client.patch(f"{BASE}/{acme['id']}", json={"hq_project_id": world.ids["alpha"]})
    assert set_.status_code == 200 and set_.json()["hq_project_id"] == world.ids["alpha"]
    assert client.patch(f"{BASE}/{acme['id']}", json={"hq_project_id": 9999}).status_code == 404
    assert client.patch(f"{BASE}/{acme['id']}", json={"hq_project_id": None}).json()["hq_project_id"] is None
    assert client.patch(f"{BASE}/{acme['id']}", json={}).status_code == 422


def test_project_list_carries_derived_parent_project_id(client, world, tmp_path):  # noqa: F811
    with closing(connect(world.db)) as conn:
        child = create_project(conn, name="alpha-support", path=str(tmp_path / "alpha" / "support"))
        create_project(conn, name="alphabet", path=str(tmp_path / "alphabet"))
    rows = {p["name"]: p for p in client.get("/api/v1/projects").json()}
    assert rows["alpha-support"]["parent_project_id"] == world.ids["alpha"]
    assert rows["alphabet"]["parent_project_id"] is None
    assert rows["alpha"]["parent_project_id"] is None and child["id"] == rows["alpha-support"]["id"]
