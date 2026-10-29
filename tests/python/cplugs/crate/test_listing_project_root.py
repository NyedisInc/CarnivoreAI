
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.crate import constants as K
from src.cplugs.crate import refs
import sqlite3
from contextlib import closing

from tests.python.inventory.world import UUID_A, UUID_D
from tests.python.cplugs.crate.api_world import BASE, ApiWorld, export
from tests.python.cplugs.crate.test_jobs import _bundle_ids  # noqa: F401


def test_listings_return_the_original_project_root_and_null_when_there_is_none(tmp_path: Path,
                                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        project = export(api, client, {"scope": "project", "target": api.world.root1, "variant": "own"})
        assert project.state == K.STATE_DONE, project.error
        pid = project.result["bundle_id"]
        bundles = {b["bundle_id"]: b for b in client.get(f"{BASE}/bundles").json()["bundles"]}
        assert bundles[pid]["project_root"] == api.world.root1
        assert client.get(f"{BASE}/bundles/{pid}").json()["bundle"]["project_root"] == api.world.root1
        crates = {c["bundle_id"]: c for c in client.get(f"{BASE}/folders/primary/crates").json()["crates"]}
        assert crates[pid]["project_root"] == api.world.root1
        home = export(api, client, {"scope": "session", "target": UUID_A, "variant": "own"})
        assert client.get(f"{BASE}/bundles/{home.result['bundle_id']}").json()["bundle"]["project_root"] == api.world.root1
        with closing(sqlite3.connect(api.world.main)) as conn, conn:
            conn.execute("UPDATE sessions SET project_id = NULL WHERE id = ?", (api.world.row_d,))
        loose = export(api, client, {"scope": "session", "target": UUID_D, "variant": "own"})
        assert loose.state == K.STATE_DONE, loose.error
        assert client.get(f"{BASE}/bundles/{loose.result['bundle_id']}").json()["bundle"]["project_root"] is None
        assert all(b["project_root"] is None for bid, b in bundles.items() if bid not in (pid, home.result['bundle_id'], loose.result['bundle_id']))


def test_project_root_of_is_null_for_a_file_that_is_not_a_crate_and_for_an_encrypted_one(tmp_path: Path) -> None:
    junk = tmp_path / "crate-x.crate"
    junk.write_bytes(b"not a crate")
    assert refs.project_root_of(junk) is None
    assert refs.project_root_of(tmp_path / "crate-y.crate.age") is None
    assert refs.project_root_of(tmp_path / "gone.crate") is None
