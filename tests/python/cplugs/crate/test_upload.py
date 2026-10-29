
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Dict, Tuple

import pytest

from src.cplugs.crate import folders, upload
from tests.python.cplugs.crate.api_world import BASE, ApiWorld, export, stop_runner
from tests.python.cplugs.crate.crate_world import UUID_A

SESSION = {"scope": "session", "target": UUID_A, "variant": "own"}
URL = f"{BASE}/folders/primary/crates/upload"
NEW_NAME = "crate-20261019T000000Z-session-fromanothermac.crate"


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def _crate_bytes(api: ApiWorld, client) -> Tuple[bytes, str]:
    import hashlib

    export(api, client, SESSION)
    listed = client.get(f"{BASE}/folders/primary/crates").json()["crates"]
    data = (folders.resolve(api.env, "primary") / listed[0]["name"]).read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def _send(client, name: str, data: bytes, sha: str | None = None):
    headers: Dict[str, str] = {"X-Crate-Name": name, "Content-Type": "application/octet-stream"}
    if sha:
        headers["X-Crate-Sha256"] = sha
    return client.post(URL, content=data, headers=headers)


def _leftovers(folder: Path) -> list:
    return [p.name for p in folder.iterdir() if p.name.endswith(".partial")]


def test_receives_a_crate_beside_its_checksum_and_lists_it_as_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        data, sha = _crate_bytes(api, client)
        folder = folders.resolve(api.env, "primary")
        api.published.clear()
        answer = _send(client, NEW_NAME, data, sha)
        assert answer.status_code == 201, answer.text
        assert answer.json() == {"name": NEW_NAME, "size": len(data), "sha256": sha, "sidecar": True,
                                   "project_root": api.world.root1}
        assert (folder / NEW_NAME).read_bytes() == data
        assert stat.S_IMODE(os.stat(folder / NEW_NAME).st_mode) == 0o600
        assert (folder / f"{NEW_NAME}.sha256").read_text().split()[0] == sha
        assert _leftovers(folder) == []
        assert "cplug.crate.jobs" in api.published
        listed = {c["name"]: c for c in client.get(f"{BASE}/folders/primary/crates").json()["crates"]}
        assert listed[NEW_NAME]["bundle_id"] is None and listed[NEW_NAME]["sha256_sidecar"] == sha
        assert listed[NEW_NAME]["project_root"] == api.world.root1


def test_refuses_to_overwrite_and_refuses_a_bad_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        data, _sha = _crate_bytes(api, client)
        folder = folders.resolve(api.env, "primary")
        assert _send(client, NEW_NAME, data).status_code == 201
        before = (folder / NEW_NAME).read_bytes()
        again = _send(client, NEW_NAME, b"something else")
        assert again.status_code == 409 and again.json()["detail"]["code"] == "name_taken"
        assert (folder / NEW_NAME).read_bytes() == before and _leftovers(folder) == []
        for bad in ("../crate-x-1234.crate", "share-x-1234.crate", "crate-x.zip", "crate-x-1234.crate/../y", "", "sub/crate-x-1234.crate"):
            refused = _send(client, bad, data)
            assert refused.status_code == 422 and refused.json()["detail"]["code"] == "bad_crate_name", bad
        assert _leftovers(folder) == []


def test_a_bad_file_removes_the_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        data, sha = _crate_bytes(api, client)
        folder = folders.resolve(api.env, "primary")
        wrong = _send(client, NEW_NAME, data, "0" * 64)
        assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "sha256_mismatch"
        garbage = _send(client, NEW_NAME, b"not a crate at all" * 100, None)
        assert garbage.status_code == 422 and garbage.json()["detail"]["code"] == "crate_unreadable"
        not_hex = _send(client, NEW_NAME, data, "zz")
        assert not_hex.status_code == 422 and not_hex.json()["detail"]["code"] == "bad_sha256"
        fake_age = _send(client, "crate-x-1234.crate.age", b"plain bytes, no age header", None)
        assert fake_age.status_code == 422 and fake_age.json()["detail"]["code"] == "crate_unreadable"
        assert not (folder / NEW_NAME).exists() and _leftovers(folder) == []

        def boom(temp: Path, final: Path) -> None:
            raise OSError("disk went away")

        monkeypatch.setattr(upload, "publish", boom)
        with pytest.raises(OSError):
            _send(client, NEW_NAME, data, sha)
        assert not (folder / NEW_NAME).exists() and _leftovers(folder) == []


def test_refuses_when_the_volume_has_no_room(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        data, _sha = _crate_bytes(api, client)
        monkeypatch.setattr(folders, "free_bytes", lambda _path: 0)
        full = _send(client, NEW_NAME, data)
        assert full.status_code == 507 and full.json()["detail"]["code"] == "no_space"
        assert _leftovers(folders.resolve(api.env, "primary")) == []
