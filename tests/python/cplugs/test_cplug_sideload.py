
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.core.db_migration import ensure_db_migrated
from src.cplugs.host import identity, runtime, sideload, sidecar_boot, sidecar_registry
from src.cplugs.host import state as owner_state
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401

URL = "/api/v1/cplug-owner/sideload"
NAME = "devclock"


def write_plugin(folder, body: str = "print('tick')\n") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": 1, "id": NAME, "name": "Dev Clock", "description": "Tells the time.", "version": "1.0.0", "entry": "main.py",
                "tools": [], "permissions": {"app": ["notify"]}}
    (folder / "cplug.json").write_text(json.dumps(manifest))
    (folder / "main.py").write_text(body)


@pytest.fixture
def world(tmp_path, client, owner_jwt, key_store, monkeypatch):  # noqa: F811
    from src.main import app

    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    host = SimpleNamespace(state_dir=state, publish=lambda topic: None, install_key=lambda name: name)
    rt = sidecar_boot.SidecarRuntime(host, app, asyncio.new_event_loop(), env_safe=lambda: False, app_version="9.9.9")
    app.state.sidecar_runtime = rt
    app.state.cplugs_host = runtime.Host(state, app)
    clock = SimpleNamespace(t=1_000_000.0)
    monkeypatch.setattr(sideload, "wall", lambda: clock.t)
    src = tmp_path / "src" / NAME
    write_plugin(src)
    _row, secret = key_store.create("script")
    try:
        yield SimpleNamespace(client=client, state=state, clock=clock, src=src, owner=bearer(owner_jwt), key=bearer(secret), rt=rt)
    finally:
        del app.state.sidecar_runtime, app.state.cplugs_host
        sidecar_registry.install(None)


def post(w, headers=None, **body):
    return w.client.post(URL, json={"path": str(w.src), **body}, headers=headers or w.owner)


def test_fence_and_switch_then_unverified_local_row_then_edit_needs_approval_then_twelve_hours(world):
    w = world
    for method, url, body in (("post", URL, {"path": str(w.src)}), ("delete", f"{URL}?name={NAME}", None), ("put", f"{URL}/switch", {"enabled": True})):
        r = getattr(w.client, method)(url, headers=w.key, **({"json": body} if body else {}))
        assert r.status_code == 403 and r.json()["detail"] == {"reason": "api_key_forbidden"}, (method, r.text)
    assert not sideload.is_on(w.state, lambda: w.clock.t)

    r = post(w)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sideload_off", r.text
    assert not (w.state / "cplug-code" / NAME).exists()

    assert w.client.put(f"{URL}/switch", json={"enabled": True}, headers=w.owner).json()["enabled"] is True
    r = post(w)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["id"] == NAME and first["tier"] == "local" and first["unverified"] is True and first["needs_approval"] is False
    root = w.state / "cplug-code" / NAME
    assert root.is_dir() and root != w.src and (root / "main.py").read_text() == "print('tick')\n"
    assert identity.lookup(w.state, NAME).catalog_id == f"local/{NAME}"
    found = sidecar_registry.find(NAME)
    assert found is not None and found.manifest.tier == "local" and found.item_id == f"local/{NAME}"

    owner_state.update(w.state, found.manifest, None, lambda s: replace(s, enabled=True, grants=("notify",), digest=found.manifest.code_digest))
    same = post(w).json()
    assert same["unchanged"] is True and same["changed"] == [] and same["needs_approval"] is False
    assert sidecar_registry.find(NAME).manifest.code_digest == owner_state.get(w.state, found.manifest).digest

    (w.src / "main.py").write_text("print('edited')\n")
    assert (root / "main.py").read_text() == "print('tick')\n"
    edited = post(w).json()
    assert edited["changed"] == ["main.py"] and edited["needs_approval"] is True and edited["digest"] != first["digest"]
    assert (root / "main.py").read_text() == "print('edited')\n"
    rows = {p["id"]: p for p in w.client.get("/api/v1/cplugs", headers=w.owner).json()["cplugs"]}
    assert rows[NAME]["unverified"] is True and rows[NAME]["trust"] == "local" and rows[NAME]["needs"] == ["notify"]
    sheet = w.client.get(f"/api/v1/cplugs/{NAME}/sheet", headers=w.owner).json()
    assert sheet["unverified"] is True and sheet["changed_files"] == ["main.py"]

    reserved = w.src.parent / "huddle"
    write_plugin(reserved)
    manifest = json.loads((reserved / "cplug.json").read_text())
    (reserved / "cplug.json").write_text(json.dumps({**manifest, "id": "huddle"}))
    r = w.client.post(URL, json={"path": str(reserved)}, headers=w.owner)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "name_reserved", r.text
    assert post(w, name="../../escape").json()["detail"]["code"] == "name_invalid"

    (w.src / "link.py").symlink_to(w.src / "main.py")
    r = post(w)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "source_unsafe", r.text
    (w.src / "link.py").unlink()

    w.clock.t += 12 * 3600 - 1
    assert sideload.is_on(w.state) and sidecar_registry.find(NAME) is not None
    w.clock.t += 1
    assert not sideload.is_on(w.state) and sidecar_registry.find(NAME) is None
    r = post(w)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sideload_off"
    assert w.client.get(URL, headers=w.owner).json()["enabled"] is False

    r = w.client.delete(f"{URL}?name={NAME}", headers=w.owner)
    assert r.status_code == 200 and not root.exists() and sidecar_registry.find(NAME) is None
    assert w.client.delete(f"{URL}?name={NAME}", headers=w.owner).status_code == 404
    assert identity.lookup(w.state, NAME) is not None


def test_expiry_timer_is_armed_at_boot_and_stops_the_sideloads(world, monkeypatch):
    from src.cplugs.host import sideload_routes
    from src.main import app

    w = world
    assert w.client.put(f"{URL}/switch", json={"enabled": True}, headers=w.owner).status_code == 200
    app.state.sideload_expiry = None
    stopped = []

    async def fake_stop_all(live):
        stopped.append(live)

    monkeypatch.setattr(sideload_routes, "stop_all_local", fake_stop_all)

    async def boot_then_fire():
        await w.rt.start()
        handle = app.state.sideload_expiry
        assert handle is not None
        handle.cancel()
        await sideload_routes._expired(w.rt)
        assert stopped == []
        w.clock.t += 12 * 3600
        await sideload_routes._expired(w.rt)

    asyncio.run(boot_then_fire())
    assert stopped == [w.rt]


def test_delete_of_a_name_that_is_not_a_sideload_stops_nothing_and_local_is_a_reserved_handle(world, monkeypatch):
    from src.cplugs.host import sideload_routes
    from src.models.catalog_names import RESERVED_PUBLISHER_HANDLES

    w = world
    stopped = []

    async def fake_stop(live, name, *, forget=False):
        stopped.append(name)

    monkeypatch.setattr(sideload_routes, "_stop", fake_stop)
    r = w.client.delete(f"{URL}?name=somecatalogplugin", headers=w.owner)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "sideload_unknown" and stopped == []
    assert "local" in RESERVED_PUBLISHER_HANDLES
