
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Tuple

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import routes as host_routes, runtime, state as owner_state
from tests.helpers import style_guide_inventory as guide
from tests.python.cplugs.owner import turn_on
from tests.helpers.catalog_text import CATALOG_PATH, REPO_ROOT, slice_paths

KEY_LINE = re.compile(r"""^\s*'(cplug\.[a-z0-9]+\.[^']*)'\s*:""", re.M)


def _setting(field: Dict[str, Any]) -> Any:
    kind = field["kind"]
    if kind == "boolean":
        return not field.get("default", False)
    if kind == "enum":
        return next(o for o in field["options"] if o != field.get("default"))
    return "x"


def _client(tmp_path: Path) -> Tuple[TestClient, runtime.Host]:
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app), host


def run_cycle(plugin_id: str, tmp_path: Path) -> Dict[str, Any]:
    d = runtime.find(plugin_id)
    assert d is not None, plugin_id
    base = f"/api/v1/cplugs/{plugin_id}"
    client, host = _client(tmp_path)
    with client:
        turn_on(host, plugin_id)
        fields = d.manifest.settings_schema.get("fields", {}) if d.manifest.settings_schema else {}
        if fields:
            name, field = next(iter(fields.items()))
            value = _setting(field)
            if name in {decl.root_setting for decl in d.manifest.data or () if decl.role == "backup_destination"}:
                (tmp_path / "chosen").mkdir(exist_ok=True)
                value = str(tmp_path / "chosen" / name)
            current = client.get(base).json()
            saved = client.put(base, json={"revision": current["revision"], "settings": {name: value}})
            assert saved.status_code == 200, saved.text
        on = client.get(base)
        assert on.json()["enabled"] is True, on.text
        folder = host.folder(plugin_id)
        (folder / "data").mkdir(parents=True, exist_ok=True)
        (folder / "data" / "blob.bin").write_bytes(b"x" * 7)
        written = [folder / "data" / "blob.bin"]
        for rel in d.manifest.owns.files:
            target = tmp_path / rel
            (target / "deep").mkdir(parents=True, exist_ok=True)
            (target / "deep" / "a.bin").write_bytes(b"y" * 5)
            (target / "b.bin").write_bytes(b"z" * 3)
            written += [target / "deep" / "a.bin", target / "b.bin"]
        assert plugin_id in owner_state.stored_ids(tmp_path)
        assert client.post(f"{base}/purge", json={}).json()["detail"]["code"] == "cplug_enabled"
        off = client.put(base, json={"revision": on.json()["revision"], "enabled": False, "confirm_dependents": True})
        assert off.status_code == 200 and off.json()["enabled"] is False, off.text
        price = client.post(f"{base}/purge", json={"dry_run": True}).json()
        assert price["files"] >= len(written) and price["dry_run"] is True
        assert all(p.exists() for p in written), "a dry run deleted something"
        stale = client.post(f"{base}/purge", json={"dry_run": False, "confirm_token": "nope"})
        assert stale.json()["detail"]["code"] == "purge_stale" and all(p.exists() for p in written)
        done = client.post(f"{base}/purge", json={"dry_run": False, "confirm_token": price["confirm_token"]})
        assert done.status_code == 200, done.text
    residue = [str(p) for p in written if p.exists()]
    residue += [str(tmp_path / rel) for rel in d.manifest.owns.files if (tmp_path / rel).exists()]
    residue += [str(folder)] if folder.exists() else []
    assert residue == [], f"purge left {residue}"
    assert plugin_id not in owner_state.stored_ids(tmp_path), "purge left the state.json entry"
    return price


def assert_no_dangling_assets(plugin_id: str) -> None:
    d = runtime.find(plugin_id)
    assert d is not None, plugin_id
    namespace = f"cplug.{plugin_id}."
    own = slice_paths().get(plugin_id)
    assert own is not None, f"{plugin_id} has no catalog slice"
    slice_keys = set(KEY_LINE.findall(own.read_text(encoding="utf-8")))
    assert slice_keys and all(k.startswith(namespace) for k in slice_keys)
    shared = set(KEY_LINE.findall(CATALOG_PATH.read_text(encoding="utf-8")))
    assert not {k for k in shared if k.startswith(namespace)}, "the shared catalog still holds the plugin's keys"
    for key in (d.manifest.name_key, d.manifest.description_key):
        assert key in slice_keys, f"{key} is not in the plugin's own slice"
    web = f"web/src/cplugs/{plugin_id}/"
    registry = json.loads(guide.REGISTRY.read_text(encoding="utf-8"))
    assert not [k for k in registry["files"] if k.startswith(web)], "registry.json still holds the plugin's rows"
    prose = [n for n, html in guide.fragment_text().items() if "/" not in n and web in html]
    assert prose == [], f"shared guide sections name the plugin's files: {prose}"
    rows = guide.plugin_rows().get(plugin_id, {})
    declared = {p for p in d.manifest.owns.style_guide}
    assert declared == set(rows), f"owns.style_guide and style-guide.json disagree: {declared ^ set(rows)}"
    prefix = f"/cplugs/{plugin_id}"
    if d.router is not None:
        assert all(r.path.startswith(prefix) for r in d.router.routes), "a route outside the plugin's prefix"
    assert set(d.tools) <= set(d.manifest.surfaces.mcp_tools), "a tool the manifest does not declare"
    assert REPO_ROOT.joinpath("src", "cplugs", plugin_id, "cplug.json").is_file()
