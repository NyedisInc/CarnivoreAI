
from __future__ import annotations

from typing import Any, Dict

from src.config.launch_profiles import LaunchProfile
from src.core.launch_profiles.store import LaunchProfileStore
from tests.python.launch_profiles.test_launch_profiles_routes import env, profile  # noqa: F401

BASE = "/api/v1/launch-profiles"
PIN = {"account": {"mode": "pinned", "account_id": "work"}}


def _refusal(response: Any) -> Dict[str, Any]:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "pin_unsupported"
    assert detail["message"] and detail["message"] != "pin_unsupported" and "work" not in detail["message"]
    return detail


def test_create_with_a_pin_is_refused_and_without_one_is_saved(env):  # noqa: F811
    c = env.client
    _refusal(c.post(BASE, json={"profile": profile("claude-pinned", **PIN)}))
    assert c.get(f"{BASE}/claude-pinned").status_code == 404
    assert c.post(BASE, json={"profile": profile("claude-free")}).status_code == 201


def test_replace_with_a_pin_is_refused(env):  # noqa: F811
    c = env.client
    _refusal(c.put(f"{BASE}/claude-main", json={"profile": profile("claude-main", **PIN)}))
    assert c.get(f"{BASE}/claude-main").json()["profile"]["account"]["mode"] == "follow_active"
    assert c.put(f"{BASE}/claude-main", json={"profile": profile("claude-main", description="x")}).status_code == 200


def test_import_with_a_pin_is_refused(env):  # noqa: F811
    c = env.client
    doc = c.get(f"{BASE}/claude-main/export").json()
    doc["profile"]["id"] = "claude-shared"
    doc["profile"]["account"] = PIN["account"]
    del doc["sha256"]
    preview = c.post(f"{BASE}/import/preview", json={"document": doc})
    sha = preview.json().get("sha256", "0" * 64) if preview.status_code == 200 else "0" * 64
    _refusal(c.post(f"{BASE}/import", json={"document": doc, "confirm_sha256": sha}))
    assert c.get(f"{BASE}/claude-shared").status_code == 404


def test_a_profile_stored_with_a_pin_still_loads_and_is_flagged(env):  # noqa: F811
    LaunchProfileStore(env.config).put(LaunchProfile.model_validate(profile("claude-old", **PIN)))
    c = env.client
    row = c.get(f"{BASE}/claude-old").json()["profile"]
    assert row["account"] == {"mode": "pinned", "account_id": "work"} and row["account_pin_unsupported"] is True
    listed = {p["id"]: p for p in c.get(BASE).json()["profiles"]}
    assert listed["claude-old"]["account_pin_unsupported"] is True and listed["claude-main"]["account_pin_unsupported"] is False
