
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from tests.python.cplugs.save.old_sources_rig import BASE, rig  # noqa: F401


def test_capture_scope_defaults_to_human_and_a_put_is_stored(rig: Any) -> None:
    client, state, _ = rig
    first = client.get(f"{BASE}/capture-scope").json()
    assert first["capture_scope"] == "human" and "all" in first["choices"]
    put = client.put(f"{BASE}/capture-scope", json={"capture_scope": "all"})
    assert put.status_code == 200, put.text
    assert put.json()["capture_scope"] == "all"
    assert client.get(f"{BASE}/capture-scope").json()["capture_scope"] == "all"
    stored = json.loads((state / "config.json").read_text())
    assert "all" in json.dumps(stored)


def test_capture_scope_refuses_a_value_that_is_not_a_scope(rig: Any) -> None:
    client, state, _ = rig
    before = (state / "config.json").read_text()
    assert client.put(f"{BASE}/capture-scope", json={"capture_scope": "everything"}).status_code == 422
    assert (state / "config.json").read_text() == before


def test_scope_and_review_routes_need_the_bearer(rig: Any) -> None:
    client, _, _ = rig
    client.app.dependency_overrides.pop(require_auth, None)
    anonymous = TestClient(client.app)
    assert anonymous.get(f"{BASE}/capture-scope").status_code == 401
    assert anonymous.put(f"{BASE}/capture-scope", json={"capture_scope": "all"}).status_code == 401
    review = {"units": ["u"], "verdict": "keep", "date": "20261022"}
    assert anonymous.post(f"{BASE}/imports/review", json=review).status_code == 401


def test_review_refuses_a_verdict_that_is_not_keep_or_junk(rig: Any) -> None:
    client, _, _ = rig
    resp = client.post(f"{BASE}/imports/review", json={"units": ["u"], "verdict": "maybe", "date": "20261022"})
    assert 400 <= resp.status_code < 500
    assert resp.json()["detail"]["code"] == "bad_verdict"
    assert client.post(f"{BASE}/imports/review", json={"units": ["u"], "verdict": "keep", "date": "yesterday"}).status_code >= 400


def test_review_rejects_an_empty_unit_list(rig: Any) -> None:
    client, _, _ = rig
    assert client.post(f"{BASE}/imports/review", json={"units": [], "verdict": "keep", "date": "20261022"}).status_code == 422


def test_review_of_a_unit_the_vault_does_not_hold_is_reported_not_applied(rig: Any) -> None:
    client, _, _ = rig
    resp = client.post(f"{BASE}/imports/review", json={"units": ["no-such-unit"], "verdict": "keep", "date": "20261022"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert not body["updated"]
    assert body["refused"]
