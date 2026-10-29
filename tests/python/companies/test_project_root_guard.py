
from __future__ import annotations

API = "/api/v1"


def _post(client, name: str, path: str):
    return client.post(f"{API}/projects", json={"name": name, "path": path})


def test_base_folders_and_swallowing_roots_are_refused(tmp_path, client):
    assert _post(client, "child", str(tmp_path / "ws" / "child")).status_code in (200, 201)
    for base in ("~/carnivore-projects", "~/cloude-projects"):
        refused = _post(client, "base", base)
        assert refused.status_code == 409 and refused.json()["code"] == "project_root_refused", refused.text
    swallow = _post(client, "ws", str(tmp_path / "ws"))
    assert swallow.status_code == 409 and swallow.json()["code"] == "project_root_refused", swallow.text
    assert _post(client, "sibling", str(tmp_path / "ws2")).status_code in (200, 201)


def test_a_folder_holding_only_an_archived_project_is_allowed(tmp_path, client):
    assert _post(client, "old", str(tmp_path / "arch" / "old")).status_code in (200, 201)
    assert client.post(f"{API}/projects/old/archive").status_code == 200
    assert _post(client, "arch", str(tmp_path / "arch")).status_code in (200, 201)


def _case_insensitive(path) -> bool:
    import os

    probe = path / "CaseProbe"
    probe.mkdir(exist_ok=True)
    return os.path.exists(str(path / "caseprobe"))


def test_case_variants_of_a_base_folder_and_a_parent_are_refused(tmp_path, client):
    import pytest

    if not _case_insensitive(tmp_path):
        pytest.skip("the temp volume is case-sensitive: a case variant is a different folder here")
    assert _post(client, "kid", str(tmp_path / "Parent" / "kid")).status_code in (200, 201)
    for base in ("~/CARNIVORE-PROJECTS", "~/Carnivore-Projects/", "~/CLOUDE-PROJECTS"):
        refused = _post(client, "base", base)
        assert refused.status_code == 409 and refused.json()["code"] == "project_root_refused", (base, refused.text)
    swallow = _post(client, "par", str(tmp_path / "PARENT"))
    assert swallow.status_code == 409 and swallow.json()["code"] == "project_root_refused", swallow.text


def test_unicode_normalisation_variants_of_a_parent_are_refused(tmp_path, client):
    import unicodedata

    nfc = "Caf\u00e9"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    assert _post(client, "ukid", str(tmp_path / nfc / "ukid")).status_code in (200, 201)
    for parent in (nfd, nfd.upper()):
        swallow = _post(client, "upar", str(tmp_path / parent))
        assert swallow.status_code == 409 and swallow.json()["code"] == "project_root_refused", (parent, swallow.text)
    other = unicodedata.normalize("NFD", "Caf\u00e9-other")
    assert _post(client, "usib", str(tmp_path / other)).status_code in (200, 201)


def test_check_root_route_refuses_without_writing(tmp_path, client):
    assert _post(client, "kid2", str(tmp_path / "w" / "kid2")).status_code in (200, 201)
    refused = client.post(f"{API}/projects/check-root", json={"path": "~/carnivore-projects"})
    assert refused.status_code == 409 and refused.json()["code"] == "project_root_refused", refused.text
    swallow = client.post(f"{API}/projects/check-root", json={"path": str(tmp_path / "w")})
    assert swallow.status_code == 409, swallow.text
    ok = client.post(f"{API}/projects/check-root", json={"path": str(tmp_path / "elsewhere")})
    assert ok.status_code == 200 and ok.json() == {"ok": True}
