
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from src.cplugs.crate import folders, removal
from src.cplugs.crate.jobs import runner
from tests.python.cplugs.crate.api_world import BASE, ApiWorld, export, stop_runner
from tests.python.cplugs.crate.crate_world import UUID_A

SESSION = {"scope": "session", "target": UUID_A, "variant": "own"}
URL = f"{BASE}/crates/remove"


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


@pytest.fixture
def trash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "trash"
    folder.mkdir()
    monkeypatch.setattr(removal, "home_trash", lambda: folder)
    return folder


def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, second: bool = False) -> ApiWorld:
    if not second:
        return ApiWorld(tmp_path, monkeypatch)
    folder = tmp_path / "second"
    folder.mkdir()
    return ApiWorld(tmp_path, monkeypatch, secondFolder=str(folder))


def _exported(api: ApiWorld, client) -> Dict[str, Any]:
    export(api, client, SESSION)
    return client.get(f"{BASE}/bundles").json()["bundles"][0]


def test_moves_both_files_to_the_trash_and_marks_the_bundle_removed(tmp_path, monkeypatch, trash) -> None:
    api = _world(tmp_path, monkeypatch)
    with api.client() as client:
        bundle = _exported(api, client)
        primary = folders.resolve(api.env, "primary")
        name = Path(bundle["locations"][0]["where"]).name
        assert (primary / f"{name}.sha256").exists()
        api.published.clear()
        answer = client.post(URL, json={"bundle_id": bundle["bundle_id"]})
        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert body["local_removed"] is True and body["bundle_id"] == bundle["bundle_id"]
        assert not (primary / name).exists() and not (primary / f"{name}.sha256").exists()
        assert (trash / name).is_file() and (trash / f"{name}.sha256").is_file()
        assert "cplug.crate.jobs" in api.published
        row = client.get(f"{BASE}/bundles").json()["bundles"][0]
        assert row["local_removed"] is True and row["locations"][0]["state"] == "missing"
        again = client.post(URL, json={"bundle_id": bundle["bundle_id"]})
        assert again.status_code == 404 and again.json()["detail"]["code"] == "crate_not_found"


def test_a_name_in_the_trash_gets_a_free_one(tmp_path, monkeypatch, trash) -> None:
    api = _world(tmp_path, monkeypatch)
    with api.client() as client:
        bundle = _exported(api, client)
        name = Path(bundle["locations"][0]["where"]).name
        (trash / name).write_bytes(b"older")
        body = client.post(URL, json={"folder": "primary", "name": name}).json()
        assert (trash / name).read_bytes() == b"older"
        landed = Path(body["removed"][0]["trash"])
        assert landed.name != name and landed.is_file()


def test_only_the_named_folder_goes_unless_the_second_copy_is_asked_for(tmp_path, monkeypatch, trash) -> None:
    api = _world(tmp_path, monkeypatch, second=True)
    with api.client() as client:
        bundle = _exported(api, client)
        name = Path(bundle["locations"][0]["where"]).name
        second = folders.resolve(api.env, "second")
        first = client.post(URL, json={"bundle_id": bundle["bundle_id"]}).json()
        assert (second / name).exists() and first["local_removed"] is False
        assert client.get(f"{BASE}/bundles").json()["bundles"][0]["local_removed"] is False
        last = client.post(URL, json={"folder": "second", "name": name}).json()
        assert not (second / name).exists() and last["local_removed"] is True


def test_also_second_takes_the_other_copy_too(tmp_path, monkeypatch, trash) -> None:
    api = _world(tmp_path, monkeypatch, second=True)
    with api.client() as client:
        bundle = _exported(api, client)
        name = Path(bundle["locations"][0]["where"]).name
        body = client.post(URL, json={"bundle_id": bundle["bundle_id"], "also_second": True}).json()
        assert [r["folder"] for r in body["removed"]] == ["primary", "second"] and body["local_removed"] is True
        assert not (folders.resolve(api.env, "second") / name).exists()


def test_a_found_unrecorded_crate_goes_without_touching_any_record(tmp_path, monkeypatch, trash) -> None:
    api = _world(tmp_path, monkeypatch)
    with api.client() as client:
        primary = folders.resolve(api.env, "primary")
        name = "crate-20261019T000000Z-session-fromanothermac.crate"
        (primary / name).write_bytes(b"x")
        body = client.post(URL, json={"folder": "primary", "name": name}).json()
        assert body["bundle_id"] is None and body["local_removed"] is False
        assert (trash / name).read_bytes() == b"x" and not (primary / name).exists()


@pytest.mark.parametrize("name", ["../crate-x-1.crate", "crate-x/../../y.crate", "/etc/passwd", "share-x-1.crate",
                                  "notes.txt", "crate-a.crate/../crate-b.crate"])
def test_refuses_a_path_or_a_name_that_is_not_a_plain_crate(tmp_path, monkeypatch, trash, name) -> None:
    api = _world(tmp_path, monkeypatch)
    with api.client() as client:
        primary = folders.resolve(api.env, "primary")
        (tmp_path / "crate-x-1.crate").write_bytes(b"outside")
        answer = client.post(URL, json={"folder": "primary", "name": name})
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "bad_crate_name"
        assert (tmp_path / "crate-x-1.crate").exists() and list(trash.iterdir()) == [] and primary.exists()


def test_refuses_a_symlink_and_a_missing_file(tmp_path, monkeypatch, trash) -> None:
    api = _world(tmp_path, monkeypatch)
    with api.client() as client:
        primary = folders.resolve(api.env, "primary")
        target = tmp_path / "elsewhere.bin"
        target.write_bytes(b"x")
        (primary / "crate-20261019T000000Z-session-link.crate").symlink_to(target)
        link = client.post(URL, json={"folder": "primary", "name": "crate-20261019T000000Z-session-link.crate"})
        assert link.status_code == 422 and link.json()["detail"]["code"] == "crate_refused" and target.exists()
        gone = client.post(URL, json={"folder": "primary", "name": "crate-20261019T000000Z-session-gone.crate"})
        assert gone.status_code == 404 and gone.json()["detail"]["code"] == "crate_not_found"
        assert client.post(URL, json={"folder": "primary"}).status_code == 422
        assert client.post(URL, json={"bundle_id": "crate-nope"}).json()["detail"]["code"] == "bundle_not_found"


def test_refuses_while_a_job_runs_on_that_crate(tmp_path, monkeypatch, trash) -> None:
    api = _world(tmp_path, monkeypatch)
    with api.client() as client:
        bundle = _exported(api, client)
        name = Path(bundle["locations"][0]["where"]).name
        primary = folders.resolve(api.env, "primary")
        monkeypatch.setattr(runner, "running_request", lambda: {"bundle_id": bundle["bundle_id"], "level": "full"})
        by_id = client.post(URL, json={"bundle_id": bundle["bundle_id"]})
        assert by_id.status_code == 409 and by_id.json()["detail"]["code"] == "crate_in_use"
        monkeypatch.setattr(runner, "running_request", lambda: {"source": {"folder": "primary", "name": name}})
        by_name = client.post(URL, json={"folder": "primary", "name": name})
        assert by_name.status_code == 409 and (primary / name).exists() and list(trash.iterdir()) == []
        monkeypatch.setattr(runner, "running_request", lambda: {"bundle_id": "crate-other"})
        assert client.post(URL, json={"bundle_id": bundle["bundle_id"]}).status_code == 200


def test_needs_the_owner_sign_in(tmp_path, monkeypatch, trash) -> None:
    api = _world(tmp_path, monkeypatch)
    with api.client(authed=False) as client:
        assert client.post(URL, json={"folder": "primary", "name": "crate-x-1.crate"}).status_code in (401, 403)
