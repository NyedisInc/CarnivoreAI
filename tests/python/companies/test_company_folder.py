
from __future__ import annotations

import os
from contextlib import closing

import pytest

from src.core.companies.ddl import common_project_folder
from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain

API = "/api/v1"


def _company(conn, name):
    cur = conn.execute("INSERT INTO companies (name, created_at, updated_at) VALUES (?, 'x', 'x')", (name,))
    return cur.lastrowid


def _project(conn, name, root, company_id):
    conn.execute(
        "INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at, company_id) "
        "VALUES (?, ?, ?, 'user', 'x', 'x', ?)", (root, root, name, company_id))


def test_v104_database_upgrades_and_backfills_only_by_the_safe_rule(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    for rel in ("Org/Acme/Apex/support", "Org/Personal/a", "Org/Personal/b", "Org/Personal/c", "Org/Solo/only"):
        (home / rel).mkdir(parents=True)
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 104)
        assert "folder" not in {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
        shared, nested, split, remote, gone, none = (_company(conn, n) for n in ("Personal", "Apex", "Split", "Remote", "Gone", "Empty"))
        _project(conn, "a", str(home / "Org/Personal/a"), shared)
        _project(conn, "b", str(home / "Org/Personal/b"), shared)
        _project(conn, "am", str(home / "Org/Acme/Apex"), nested)
        _project(conn, "sup", str(home / "Org/Acme/Apex/support"), nested)
        _project(conn, "s1", str(home / "Org/Personal/c"), split)
        _project(conn, "s2", str(home / "Org/Solo/only"), split)
        _project(conn, "r1", "ssh://far/x/a", remote)
        _project(conn, "g1", str(home / "Org/Missing/a"), gone)
        with conn:
            run_chain(conn, 104, 105)
        rows = {r["name"]: r["folder"] for r in conn.execute("SELECT name, folder FROM companies")}
    assert CURRENT_SCHEMA_VERSION >= 105
    assert rows["Personal"] == str(home / "Org/Personal")
    assert rows["Apex"] == str(home / "Org/Acme/Apex")
    assert rows["Split"] == str(home / "Org")
    assert rows["Remote"] is None and rows["Gone"] is None and rows["Empty"] is None


def test_backfill_never_picks_home_or_above(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "a").mkdir(parents=True)
    (home / "b").mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert common_project_folder([str(home / "a"), str(home / "b")]) is None
    assert common_project_folder([]) is None


def test_step_is_idempotent_and_keeps_a_stored_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from src.core.companies.ddl import apply_v105

    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 104)
        with conn:
            run_chain(conn, 104, 105)
            conn.execute("INSERT INTO companies (name, created_at, updated_at, folder) VALUES ('K', 'x', 'x', '/kept')")
            apply_v105(conn)
        assert conn.execute("SELECT folder FROM companies WHERE name = 'K'").fetchone()[0] == "/kept"


def _make(client, name):
    r = client.post(f"{API}/companies", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def test_folder_is_listed_set_canonicalised_validated_and_cleared(client, world, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    real = tmp_path / "Org" / "Acme" / "Globex"
    real.mkdir(parents=True)
    link = tmp_path / "short"
    link.symlink_to(tmp_path / "Org")
    (tmp_path / "afile").write_text("x")
    co = _make(client, "Globex")
    assert co["folder"] is None

    ok = client.patch(f"{API}/companies/{co['id']}", json={"folder": str(link / "Acme" / "Globex")})
    assert ok.status_code == 200, ok.text
    assert ok.json()["folder"] == str(real.resolve())
    assert [c["folder"] for c in client.get(f"{API}/companies").json()["companies"]] == [str(real.resolve())]

    for bad in (str(tmp_path / "missing"), str(tmp_path / "afile"), "/etc", "   ", str(tmp_path)):
        r = client.patch(f"{API}/companies/{co['id']}", json={"folder": bad})
        assert r.status_code == 422, (bad, r.text)
    assert client.patch(f"{API}/companies/9999", json={"folder": str(real)}).status_code == 404
    assert client.get(f"{API}/companies").json()["companies"][0]["folder"] == str(real.resolve())

    cleared = client.patch(f"{API}/companies/{co['id']}", json={"folder": None})
    assert cleared.status_code == 200 and cleared.json()["folder"] is None


def test_project_created_with_a_company_is_filed_in_the_same_call(client, world, tmp_path):
    co = _make(client, "Globex")
    made = client.post(f"{API}/projects", json={"name": "invoice sync", "path": str(tmp_path / "invoice-sync"), "company_id": co["id"]})
    assert made.status_code == 201, made.text
    assert made.json()["company_id"] == co["id"] and made.json()["company_name"] == "Globex"
    row = next(p for p in client.get(f"{API}/projects").json() if p["name"] == "invoice sync")
    assert row["company_id"] == co["id"]


def test_unknown_company_creates_nothing(client, world, tmp_path):
    made = client.post(f"{API}/projects", json={"name": "ghost", "path": str(tmp_path / "ghost"), "company_id": 999})
    assert made.status_code == 404
    assert all(p["name"] != "ghost" for p in client.get(f"{API}/projects").json())


def test_create_without_a_company_still_works(client, world, tmp_path):
    made = client.post(f"{API}/projects", json={"name": "plain", "path": str(tmp_path / "plain")})
    assert made.status_code == 201 and made.json().get("company_id") is None
