
from __future__ import annotations

import pytest

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


@pytest.fixture(autouse=True)
def upload_cap(monkeypatch):
    from types import SimpleNamespace

    from src.config import settings

    cap = SimpleNamespace(max_size_mb=10)
    monkeypatch.setattr(type(settings), "load_auth_config", lambda self: SimpleNamespace(uploads=cap), raising=True)
    return cap


def _company(client, name="Acme"):
    return client.post(f"{API}/companies", json={"name": name}).json()


def _up(client, url, data, name="x.png"):
    return client.put(url, files={"file": (name, data, "application/octet-stream")})


def test_company_upload_get_listing_and_delete(client, world):
    c = _company(client)
    assert c["has_image"] is False and c["image_rev"] is None
    assert client.get(f"{API}/companies/{c['id']}/image").status_code == 404
    r = _up(client, f"{API}/companies/{c['id']}/image", PNG, "a.txt")
    assert r.status_code == 200 and r.json()["has_image"] is True and r.json()["image_rev"]
    g = client.get(f"{API}/companies/{c['id']}/image")
    assert g.status_code == 200 and g.content == PNG and g.headers["content-type"] == "image/png"
    assert "no-cache" in g.headers["cache-control"]
    listed = client.get(f"{API}/companies").json()["companies"][0]
    assert listed["has_image"] is True and listed["image_rev"] == r.json()["image_rev"]
    assert _up(client, f"{API}/companies/{c['id']}/image", JPG).status_code == 200
    assert client.get(f"{API}/companies/{c['id']}/image").headers["content-type"] == "image/jpeg"
    assert len(list((world.state_dir / "company_images").iterdir())) == 1
    assert client.delete(f"{API}/companies/{c['id']}/image").json() == {"has_image": False, "image_rev": None}
    assert client.get(f"{API}/companies/{c['id']}/image").status_code == 404
    assert client.get(f"{API}/companies").json()["companies"][0]["has_image"] is False


def test_refusals_svg_junk_oversize_unknown(client, world, upload_cap):
    c = _company(client)
    url = f"{API}/companies/{c['id']}/image"
    assert _up(client, url, b"<svg xmlns='http://www.w3.org/2000/svg'/>", "a.png").status_code == 415
    assert _up(client, url, b"#!/bin/sh\n", "a.png").status_code == 415
    upload_cap.max_size_mb = 0
    assert _up(client, url, PNG).status_code == 413
    assert not (world.state_dir / "company_images").exists()
    assert _up(client, f"{API}/companies/9999/image", PNG).status_code == 404
    assert client.get(f"{API}/companies/9999/image").status_code == 404
    assert client.delete(f"{API}/companies/9999/image").status_code == 404
    assert client.get(f"{API}/companies/abc/image").status_code == 404


def test_project_image_and_listings(client, world):
    assert _up(client, f"{API}/projects/nope/image", PNG).status_code == 404
    r = _up(client, f"{API}/projects/alpha/image", PNG)
    assert r.status_code == 200 and r.json()["has_image"] is True
    assert client.get(f"{API}/projects/alpha/image").content == PNG
    assert client.get(f"{API}/projects/beta/image").status_code == 404
    rows = {p["name"]: p for p in client.get(f"{API}/projects").json()}
    assert rows["alpha"]["has_image"] is True and rows["alpha"]["image_rev"] == r.json()["image_rev"]
    assert rows["beta"]["has_image"] is False and rows["beta"]["image_rev"] is None
    hist = client.get(f"{API}/projects/history").json()
    entries = {g["project"]["name"]: g["project"] for g in hist["groups"] if g.get("project")}
    assert entries["alpha"]["has_image"] is True and entries["beta"]["has_image"] is False
    put = client.put(f"{API}/projects/alpha/company", json={"company_id": None}).json()
    assert put["has_image"] is True
    assert client.delete(f"{API}/projects/alpha/image").json() == {"has_image": False, "image_rev": None}


def test_files_removed_when_the_row_is_deleted(client, world):
    c = _company(client)
    _up(client, f"{API}/companies/{c['id']}/image", PNG)
    _up(client, f"{API}/projects/beta/image", PNG)
    assert client.delete(f"{API}/companies/{c['id']}").status_code == 200
    assert client.delete(f"{API}/projects/beta").status_code == 200
    assert list((world.state_dir / "company_images").iterdir()) == []
    assert list((world.state_dir / "project_images").iterdir()) == []
