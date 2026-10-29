
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from src.cplugs.crate import download, folders
from tests.python.cplugs.crate.api_world import BASE, ApiWorld, export, stop_runner
from tests.python.cplugs.crate.crate_world import UUID_A

SESSION = {"scope": "session", "target": UUID_A, "variant": "own"}


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def _exported(api: ApiWorld, client) -> Dict[str, Any]:
    export(api, client, SESSION)
    return client.get(f"{BASE}/bundles").json()["bundles"][0]


def test_sends_the_exact_bytes_as_an_attachment(tmp_path, monkeypatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        bundle = _exported(api, client)
        primary = folders.resolve(api.env, "primary")
        name = Path(bundle["locations"][0]["where"]).name
        for url in (f"{BASE}/bundles/{bundle['bundle_id']}/download", f"{BASE}/folders/primary/crates/{name}/download"):
            got = client.get(url)
            assert got.status_code == 200, got.text
            assert got.content == (primary / name).read_bytes()
            assert got.headers["content-disposition"].startswith("attachment") and name in got.headers["content-disposition"]
            assert got.headers["x-content-type-options"] == "nosniff"
        side = client.get(f"{BASE}/folders/primary/crates/{name}/download?part=sha256")
        assert side.status_code == 200 and side.content == (primary / f"{name}.sha256").read_bytes()
        assert f"{name}.sha256" in side.headers["content-disposition"]
        assert client.get(f"{BASE}/bundles/{bundle['bundle_id']}/download?part=sha256").content == side.content


def test_streams_from_disk_and_never_reads_the_file(tmp_path, monkeypatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        bundle = _exported(api, client)
        name = Path(bundle["locations"][0]["where"]).name
        path, _file_name = download.locate_blocking(api.env, download.CrateRef(folder="primary", name=name), "crate")
        response = _run(download.download(api.ctx, download.CrateRef(folder="primary", name=name)))
        assert type(response).__name__ == "FileResponse" and Path(response.path) == path


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_refuses_traversal_unknown_names_and_symlinks(tmp_path, monkeypatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        bundle = _exported(api, client)
        primary = folders.resolve(api.env, "primary")
        name = Path(bundle["locations"][0]["where"]).name
        secret = tmp_path / "outside.crate"
        secret.write_bytes(b"OUTSIDE-SECRET-BYTES")
        (primary / "crate-link.crate").symlink_to(secret)
        for bad in ("..%2F..%2Fetc%2Fpasswd", "crate-..%2Fx.crate", "notacrate.txt", f"{name}.sha256", "crate-.crate", "crate-x.crate%00"):
            got = client.get(f"{BASE}/folders/primary/crates/{bad}/download")
            assert got.status_code in (404, 422), (bad, got.status_code)
            assert b"OUTSIDE-SECRET-BYTES" not in got.content
        assert client.get(f"{BASE}/folders/primary/crates/crate-unknown-name.crate/download").status_code == 404
        refused = client.get(f"{BASE}/folders/primary/crates/crate-link.crate/download")
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == "crate_refused"
        assert client.get(f"{BASE}/folders/primary/crates/{name}/download?part=bogus").status_code == 422
        assert client.get(f"{BASE}/folders/other/crates/{name}/download").status_code == 422
        assert client.get(f"{BASE}/bundles/crate-nope/download").status_code == 404


def test_a_missing_sidecar_is_404_and_needs_the_login(tmp_path, monkeypatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        bundle = _exported(api, client)
        primary = folders.resolve(api.env, "primary")
        name = Path(bundle["locations"][0]["where"]).name
        (primary / f"{name}.sha256").unlink()
        got = client.get(f"{BASE}/folders/primary/crates/{name}/download?part=sha256")
        assert got.status_code == 404 and got.json()["detail"]["code"] == "sidecar_not_found"
    with api.client(authed=False) as anon:
        assert anon.get(f"{BASE}/folders/primary/crates/{name}/download").status_code in (401, 403)


def test_a_bundle_copy_outside_the_configured_folders_is_not_served(tmp_path, monkeypatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        bundle = _exported(api, client)
        primary = folders.resolve(api.env, "primary")
        name = Path(bundle["locations"][0]["where"]).name
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (primary / name).rename(elsewhere / name)
        monkeypatch.setattr(download.refs, "reachable", lambda b: [(0, elsewhere / name)])
        got = client.get(f"{BASE}/bundles/{bundle['bundle_id']}/download")
        assert got.status_code == 409 and got.json()["detail"]["code"] == "bundle_not_in_folder"
