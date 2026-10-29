
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict

import httpx
from fastapi import FastAPI

from src.api.auth import require_auth
from src.cplugs.host import identity, routes as host_routes, runtime, secret_store

NAME, ITEM = "clock", "acme/clock"
KEYCHAIN: Dict[Any, str] = {}
FAULT = {"on": True}


class FlakyKeychain:

    def read(self, service, account):
        return KEYCHAIN.get((service, account))

    def write(self, service, account, secret):
        KEYCHAIN[(service, account)] = secret

    def delete(self, service, account):
        if FAULT["on"]:
            raise OSError("keychain locked")
        return KEYCHAIN.pop((service, account), None) is not None


def test_failed_keychain_delete_keeps_the_name_and_a_second_purge_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_store, "_Login", FlakyKeychain)
    KEYCHAIN.clear()
    FAULT["on"] = True
    state = tmp_path / "state"
    state.mkdir()
    record = identity.register_install(state, NAME, ITEM, {d.id for d in runtime.definitions()})
    secret_store.SecretStore(state)._write({record.uuid: {"token": ["api.example.com"]}})
    KEYCHAIN[(identity.keychain_service(record.uuid), "token")] = "s3cret"
    data = identity.data_dir(state, record.uuid)
    data.mkdir(parents=True)
    (data / "note.txt").write_text("x")
    forgot, resolved = [], []

    async def go() -> None:
        app = FastAPI()
        host = runtime.install(app, state)
        host.publish = lambda *_: None
        app.state.sidecar_runtime = SimpleNamespace(supervisor=SimpleNamespace(forget=forgot.append), resolve_alerts=resolved.append)
        app.include_router(host_routes.router, prefix="/api/v1")
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        base = f"/api/v1/cplugs/{NAME}/purge"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
            price = (await http.post(base, json={"dry_run": True})).json()
            body = {"dry_run": False, "confirm_token": price["confirm_token"]}
            first = await http.post(base, json=body)
            detail = first.json()["detail"]
            assert first.status_code == 503 and detail["code"] == "cplug_purge_incomplete" and detail["stores"] == ["keychain"]
            assert identity.lookup(state, NAME).uuid == record.uuid
            assert KEYCHAIN and resolved == [NAME] and forgot == [NAME]
            FAULT["on"] = False
            price = (await http.post(base, json={"dry_run": True})).json()
            second = await http.post(base, json={"dry_run": False, "confirm_token": price["confirm_token"]})
            assert second.status_code == 200, second.text

    asyncio.run(go())
    assert identity.lookup(state, NAME) is None
    assert not KEYCHAIN and resolved == [NAME, NAME]
