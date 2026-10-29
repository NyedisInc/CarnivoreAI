
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import routes as host_routes, runtime
from tests.python.cplugs.owner import turn_on


class _Store:

    def __init__(self, live: List[str], fail: bool = False) -> None:
        self.live = [SimpleNamespace(id=i) for i in live]
        self.revoked: List[str] = []
        self.fail = fail

    async def list_live(self) -> List[Any]:
        return list(self.live)

    async def revoke(self, link_id: str) -> None:
        if self.fail:
            raise sqlite3.OperationalError("database is locked")
        self.revoked.append(link_id)
        self.live = [link for link in self.live if link.id != link_id]


def _purge_client(tmp_path: Path, store: Any) -> TestClient:
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    app.state.spectator_links = store
    app.state.relay = None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    turn_on(host, "share")
    (host.folder("share") / "data").mkdir(parents=True)
    (host.folder("share") / "data" / "x.bin").write_bytes(b"x")
    return TestClient(app)


def _off_and_priced(client: TestClient) -> dict:
    row = client.get("/api/v1/cplugs/share").json()
    assert client.put("/api/v1/cplugs/share", json={"revision": row["revision"], "enabled": False}).status_code == 200
    return client.post("/api/v1/cplugs/share/purge", json={"dry_run": True}).json()


def test_purge_revokes_every_live_link_before_deleting(tmp_path: Path) -> None:
    store = _Store(["lnk_1", "lnk_2"])
    with _purge_client(tmp_path, store) as client:
        price = _off_and_priced(client)
        assert store.revoked == [], "pricing a purge must not revoke anything"
        done = client.post("/api/v1/cplugs/share/purge", json={"dry_run": False, "confirm_token": price["confirm_token"]})
    assert done.status_code == 200, done.text
    assert sorted(store.revoked) == ["lnk_1", "lnk_2"] and store.live == []
    assert not (tmp_path / "cplugs" / "share").exists()


def test_a_purge_that_cannot_revoke_deletes_nothing(tmp_path: Path) -> None:
    store = _Store(["lnk_1"], fail=True)
    with _purge_client(tmp_path, store) as client:
        price = _off_and_priced(client)
        refused = client.post("/api/v1/cplugs/share/purge", json={"dry_run": False, "confirm_token": price["confirm_token"]})
    assert refused.status_code == 503 and refused.json()["detail"]["code"] == "purge_prepare_failed"
    assert (tmp_path / "cplugs" / "share" / "data" / "x.bin").exists()


def test_a_missing_store_is_nothing_to_revoke(tmp_path: Path) -> None:
    with _purge_client(tmp_path, None) as client:
        price = _off_and_priced(client)
        done = client.post("/api/v1/cplugs/share/purge", json={"dry_run": False, "confirm_token": price["confirm_token"]})
    assert done.status_code == 200 and not (tmp_path / "cplugs" / "share").exists()


def test_only_share_has_a_purge_hook() -> None:
    from src.cplugs.host import system_lifecycle

    assert set(system_lifecycle.PURGE_HOOKS) == {"share"}
