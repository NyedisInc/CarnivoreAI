
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import dependencies, routes as host_routes, runtime
from src.cplugs.sdk import ManifestError, core_features
from src.cplugs.sdk.manifest import parse_manifest

ROOT = Path(__file__).resolve().parents[3]
FLOW = json.loads((ROOT / "src/cplugs/flow/cplug.json").read_text())


@pytest.fixture
def client(tmp_path: Path):
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as c:
        yield c


def put(client: TestClient, cplug_id: str, **body: Any):
    row = client.get(f"/api/v1/cplugs/{cplug_id}").json()
    return client.put(f"/api/v1/cplugs/{cplug_id}", json={"revision": row["revision"], **body})


def grants_of(client: TestClient, cplug_id: str) -> Dict[str, Any]:
    return {"app": client.get(f"/api/v1/cplugs/{cplug_id}").json()["permissions"]["app"]}


@pytest.mark.parametrize("mutate, message", [
    (lambda m: m.update(requires_core=["nope"]), "unknown core feature"),
    (lambda m: m.update(requires_core="crosstalk"), "list of names"),
    (lambda m: m.update(requires_core=["crosstalk", "crosstalk"]), "twice"),
    (lambda m: m.update(min_app_version="1.16"), "semver"),
    (lambda m: m.update(min_app_version=None), "semver"),
])
def test_a_bad_dependency_declaration_is_refused(mutate, message):
    raw = copy.deepcopy(FLOW)
    assert parse_manifest(raw).requires_core == ("crosstalk", "activity_read", "transcript_events")
    mutate(raw)
    with pytest.raises(ManifestError, match=message):
        parse_manifest(raw)


def test_flow_declares_its_real_needs():
    flow = runtime.find("flow").manifest
    assert flow.requires == ("huddle",)
    assert set(flow.requires_core) == {"crosstalk", "activity_read", "transcript_events"}
    assert flow.min_app_version == "1.16.0"
    assert all(core_features.available(c) for c in flow.requires_core)
    assert core_features.available("not_a_feature") is False


def test_every_shipped_core_requirement_is_in_the_registry_and_available():
    for d in runtime.definitions():
        for cid in d.manifest.requires_core:
            assert core_features.is_core_feature(cid) and core_features.available(cid), (d.id, cid)


def test_enable_is_refused_when_the_app_is_too_old(client, monkeypatch):
    monkeypatch.setattr(dependencies, "app_version", lambda: "1.15.9")
    refused = put(client, "flow", enabled=True, grants=grants_of(client, "flow"))
    detail = refused.json()["detail"]
    assert refused.status_code == 409 and detail["code"] == "requirements_unmet"
    assert detail["unmet"] == {"min_app_version": {"need": "1.16.0", "have": "1.15.9"}}
    assert client.get("/api/v1/cplugs/flow").json()["enabled"] is False
    monkeypatch.setattr(dependencies, "app_version", lambda: "1.16.0")
    assert put(client, "flow", enabled=True, grants=grants_of(client, "flow")).status_code == 200


def test_enable_is_refused_when_a_core_feature_is_missing(client, monkeypatch):
    monkeypatch.setattr(dependencies, "app_version", lambda: "1.16.0")
    monkeypatch.setattr(core_features, "available", lambda cid: cid != "crosstalk")
    refused = put(client, "flow", enabled=True)
    assert refused.status_code == 409 and refused.json()["detail"]["unmet"] == {"core": ["crosstalk"]}
    monkeypatch.setattr(core_features, "available", lambda cid: True)
    assert put(client, "flow", enabled=True).status_code == 200


def test_an_unknown_app_version_does_not_refuse(client, monkeypatch):
    monkeypatch.setattr(dependencies, "app_version", lambda: "")
    assert put(client, "flow", enabled=True, grants=grants_of(client, "flow")).status_code == 200


def test_a_plugin_that_requires_one_that_is_off_still_enables_and_the_row_warns(client, monkeypatch):
    monkeypatch.setattr(dependencies, "app_version", lambda: "99.0.0")
    assert put(client, "huddle", enabled=False).status_code == 200
    assert client.get("/api/v1/cplugs/huddle").json()["enabled"] is False
    assert put(client, "flow", enabled=True, grants=grants_of(client, "flow")).status_code == 200
    deps = client.get("/api/v1/cplugs/flow").json()["dependencies"]
    assert deps["plugins"] == [{"id": "huddle", "status": "off"}]
    assert deps["min_app_version"]["met"] is True


def test_disabling_a_plugin_others_need_answers_with_the_dependents_until_confirmed(client, monkeypatch):
    monkeypatch.setattr(dependencies, "app_version", lambda: "99.0.0")
    assert client.get("/api/v1/cplugs/huddle").json()["enabled"] is True
    assert put(client, "flow", enabled=True, grants=grants_of(client, "flow")).status_code == 200
    needed = client.get("/api/v1/cplugs/huddle").json()["dependencies"]["needed_by"]
    assert {"id": "flow", "enabled": True} in needed
    refused = put(client, "huddle", enabled=False)
    detail = refused.json()["detail"]
    assert refused.status_code == 409 and detail["code"] == "has_dependents" and "flow" in detail["dependents"]
    assert client.get("/api/v1/cplugs/huddle").json()["enabled"] is True
    confirmed = put(client, "huddle", enabled=False, confirm_dependents=True)
    assert confirmed.status_code == 200 and confirmed.json()["enabled"] is False
    assert confirmed.json()["blocked_by"] == []
    assert client.get("/api/v1/cplugs/flow").json()["state"] == "inert"


def test_disabling_with_no_enabled_dependent_needs_no_confirm(client):
    assert dependencies.enabled_dependents("huddle", client.app.state.cplugs_host.state_dir) == []
    assert put(client, "huddle", enabled=False).status_code == 200


def test_the_dependents_are_transitive(client, monkeypatch):
    monkeypatch.setattr(dependencies, "app_version", lambda: "99.0.0")
    defs = {d.id: d for d in runtime.definitions()}
    chained = tuple(replace(d, manifest=replace(d.manifest, requires=("flow",))) if d.id == "reviewboard" else d for d in defs.values())
    monkeypatch.setattr(runtime, "definitions", lambda: chained)
    for cid in ("flow", "reviewboard"):
        assert put(client, cid, enabled=True, grants=grants_of(client, cid)).status_code == 200
    detail = put(client, "huddle", enabled=False).json()["detail"]
    assert set(detail["dependents"]) == {"flow", "reviewboard"}

