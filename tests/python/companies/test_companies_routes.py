
from __future__ import annotations

from contextlib import closing

from src.core.db import connect

API = "/api/v1"


def _make(client, name):
    r = client.post(f"{API}/companies", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _project(client, name):
    return next(p for p in client.get(f"{API}/projects").json() if p["name"] == name)


def test_create_list_sorted_trim_and_counts(client):
    assert client.get(f"{API}/companies").json()["companies"] == []
    b = _make(client, "  beta corp ")
    a = _make(client, "Acme")
    assert b["name"] == "beta corp" and b["project_count"] == 0
    assert [c["name"] for c in client.get(f"{API}/companies").json()["companies"]] == ["Acme", "beta corp"]
    assert set(a) == {"id", "name", "project_count", "has_image", "image_rev", "hue", "parent_id", "hq_project_id"}


def test_name_validation_and_duplicate_409(client):
    _make(client, "Acme")
    assert client.post(f"{API}/companies", json={"name": "acme"}).status_code == 409
    assert client.post(f"{API}/companies", json={"name": "   "}).status_code == 422
    assert client.post(f"{API}/companies", json={"name": "x" * 81}).status_code == 422
    assert client.post(f"{API}/companies", json={"name": "x" * 80}).status_code == 201


def test_rename_and_its_errors(client):
    a = _make(client, "Acme")
    b = _make(client, "Beta")
    assert client.patch(f"{API}/companies/{a['id']}", json={"name": "Acme Inc"}).json()["name"] == "Acme Inc"
    assert client.patch(f"{API}/companies/{a['id']}", json={"name": "beta"}).status_code == 409
    assert client.patch(f"{API}/companies/{a['id']}", json={"name": ""}).status_code == 422
    assert client.patch(f"{API}/companies/9999", json={"name": "z"}).status_code == 404
    assert client.patch(f"{API}/companies/{b['id']}", json={"name": "BETA"}).status_code == 200


def test_company_hue_is_set_cleared_and_validated(client):
    a = _make(client, "Acme")
    assert a["hue"] is None
    assert client.patch(f"{API}/companies/{a['id']}", json={"hue": 145}).json()["hue"] == 145
    assert client.get(f"{API}/companies").json()["companies"][0]["hue"] == 145
    assert client.patch(f"{API}/companies/{a['id']}", json={"hue": None}).json()["hue"] is None
    for bad in ({"hue": 360}, {"hue": -1}, {}, {"name": None}, {"hue": 3, "x": 1}):
        assert client.patch(f"{API}/companies/{a['id']}", json=bad).status_code == 422, bad
    assert client.patch(f"{API}/companies/9999", json={"hue": 10}).status_code == 404


def test_company_color_is_stored_as_its_hue_and_validated(client):
    from src.core.project_colors.color_math import oklch_hue_of

    a = _make(client, "Acme")
    got = client.patch(f"{API}/companies/{a['id']}", json={"color": "#6C799F"}).json()
    assert got["hue"] == oklch_hue_of("#6c799f")
    assert client.patch(f"{API}/companies/{a['id']}", json={"color": None}).json()["hue"] is None
    for bad in ({"color": "teal"}, {"color": "#12345"}, {"color": "#6c799f", "hue": 10}):
        assert client.patch(f"{API}/companies/{a['id']}", json=bad).status_code == 422, bad


def test_assign_unassign_and_project_fields(client):
    a = _make(client, "Acme")
    assert _project(client, "alpha")["company_id"] is None and _project(client, "alpha")["company_name"] is None
    r = client.put(f"{API}/projects/alpha/company", json={"company_id": a["id"]})
    assert r.status_code == 200 and r.json()["company_id"] == a["id"] and r.json()["company_name"] == "Acme"
    assert _project(client, "alpha")["company_name"] == "Acme"
    assert client.get(f"{API}/companies").json()["companies"][0]["project_count"] == 1
    r = client.put(f"{API}/projects/alpha/company", json={"company_id": None})
    assert r.json()["company_id"] is None and r.json()["company_name"] is None
    assert client.get(f"{API}/companies").json()["companies"][0]["project_count"] == 0


def test_assign_404s(client):
    a = _make(client, "Acme")
    assert client.put(f"{API}/projects/nope/company", json={"company_id": a["id"]}).status_code == 404
    assert client.put(f"{API}/projects/alpha/company", json={"company_id": 9999}).status_code == 404


def test_delete_orphans_projects_without_deleting_them(client, world):
    a = _make(client, "Acme")
    for name in ("alpha", "beta"):
        client.put(f"{API}/projects/{name}/company", json={"company_id": a["id"]})
    r = client.delete(f"{API}/companies/{a['id']}")
    assert r.status_code == 200 and r.json() == {"deleted": True, "orphaned": 2, "children_moved": 0}
    assert client.delete(f"{API}/companies/{a['id']}").status_code == 404
    assert _project(client, "alpha")["company_id"] is None and _project(client, "beta")["company_id"] is None
    with closing(connect(world.db, create=False)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects WHERE company_id IS NOT NULL").fetchone()[0] == 0


def test_history_projects_carry_company_fields(client, world):
    a = _make(client, "Acme")
    client.put(f"{API}/projects/alpha/company", json={"company_id": a["id"]})
    body = client.get(f"{API}/projects/history").json()
    by_name = {g["project"]["name"]: g["project"] for g in body["groups"] if g.get("project")}
    assert by_name["alpha"]["company_id"] == a["id"] and by_name["alpha"]["company_name"] == "Acme"
    assert by_name["beta"]["company_id"] is None


def test_writes_notify_companies_and_projects(client, monkeypatch):
    from src.core import resource_push

    seen = []
    monkeypatch.setattr(resource_push, "notify", lambda topic, *a, **k: seen.append(topic))
    a = _make(client, "Acme")
    client.put(f"{API}/projects/alpha/company", json={"company_id": a["id"]})
    assert {"companies", "projects"} <= set(seen)
    assert "companies" in __import__("src.core.resource_push.topics", fromlist=["x"]).RESOURCE_TOPICS
