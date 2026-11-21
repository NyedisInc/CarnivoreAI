
from __future__ import annotations

import pytest

from src.config import settings
from src.core.new_project import landing_check

API = "/api/v1"


@pytest.fixture
def org(world, tmp_path, monkeypatch):
    base = tmp_path / "dev"
    for rel in ("Org/Acme/Globex/payroll", "Org/Personal"):
        (base / rel).mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (base / "Org" / "Acme" / "escape").symlink_to(tmp_path / "outside")
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: base, raising=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(landing_check, "system_temp_roots", lambda: [])
    return base / "Org"


def test_folder_tree_route_is_scoped_tagged_and_read_only(client, org):
    co = client.post(f"{API}/companies", json={"name": "Globex"}).json()
    assert client.patch(f"{API}/companies/{co['id']}", json={"folder": str(org / "Acme" / "Globex")}).status_code == 200
    r = client.get(f"{API}/projects/folder-tree")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["root"] == str(org.resolve())
    imc = next(n for n in body["nodes"] if n["name"] == "Acme")
    assert [c["name"] for c in imc["children"]] == ["Globex"]
    assert imc["children"][0]["company"] == {"id": co["id"], "name": "Globex"}
    assert client.get(f"{API}/projects/folder-tree?depth=99").status_code == 422


def test_landing_check_route_blocks_an_existing_project_and_files_the_company(client, org):
    co = client.post(f"{API}/companies", json={"name": "Globex"}).json()
    assert client.post(f"{API}/projects", json={"name": "payroll", "path": str(org / "Acme/Globex/payroll")}).status_code == 201
    clash = client.post(f"{API}/projects/landing-check", json={"path": str(org / "Acme/Globex/payroll"), "company_id": co["id"]})
    assert clash.status_code == 200 and clash.json()["ok"] is False
    assert [f["code"] for f in clash.json()["findings"]] == ["already_project"]
    fresh = client.post(f"{API}/projects/landing-check", json={"path": str(org / "Acme/Globex/new-one"), "company_id": co["id"]}).json()
    assert fresh["ok"] is True and fresh["findings"][0] == {"level": "ok", "code": "company", "params": {"company": "Globex"}}
