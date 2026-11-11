
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.cplugs.host import mcp as host_mcp
from src.cplugs.host import sidecar_registry
from tests.python.api_keys.conftest import bearer, client, key_store, owner_jwt  # noqa: F401
from tests.python.plugin_health.world import make_world

URL = "/api/v1/cplug-owner/health"


@pytest.fixture
def served(tmp_path, client, owner_jwt, key_store):  # noqa: F811
    from src.main import app

    w = make_world(tmp_path)
    w.install_catalog("acme/okclock", enabled=True)
    w.install_catalog("acme/newone")
    w.settle()
    w.rt.supervisor.override_index("okclock", True)
    w.set_index({"expires_at": "2099-01-01T00:00:00Z"})
    app.state.sidecar_runtime, app.state.cplugs_host = w.rt, w.host
    w.host.app = app
    _row, secret = key_store.create("script")
    try:
        yield SimpleNamespace(w=w, client=client, owner=bearer(owner_jwt), key=bearer(secret))
    finally:
        del app.state.sidecar_runtime, app.state.cplugs_host
        sidecar_registry.install(None)


def test_the_owner_reads_the_report_and_an_api_key_cannot(served):
    refused = served.client.get(URL, headers=served.key)
    assert refused.status_code == 403 and refused.json()["detail"] == {"reason": "api_key_forbidden"}

    r = served.client.get(URL, headers=served.owner)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {row["id"]: row for row in body["rows"]}
    assert (rows["acme/okclock"]["word"], rows["acme/okclock"]["button"]) == ("on", "turn_off")
    assert (rows["acme/newone"]["word"], rows["acme/newone"]["reason"]) == ("needs_approval", "new_install")
    assert set(body["counts"]) == {"on", "off", "needs_approval", "held"} and body["problems"] == []
    assert {"orphan_data", "removed", "stale_state", "registry_generation", "registry_source"} <= set(body)
    assert body["registry_source"] == "legacy_files" and isinstance(body["registry_generation"], int)


def test_plugins_list_carries_the_same_report_as_its_health_field(served):
    app = SimpleNamespace(state=SimpleNamespace(cplugs_host=served.w.host, sidecar_runtime=served.w.rt))
    result = asyncio.run(host_mcp.plugins_list(SimpleNamespace(app=app), SimpleNamespace(external=False), {}))
    payload = json.loads(result["content"][0]["text"])
    assert {r["id"]: r["word"] for r in payload["health"]["rows"]}["acme/okclock"] == "on"
    assert "plugins" in payload
