
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from structlog.testing import capture_logs

from src.config.auth_loader import _launch_view
from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfile
from src.core import config_writer
from src.core.launch_profiles.store import LaunchProfileStore
from tests.python.launch_profiles.test_launch_profiles_routes import env  # noqa: F401

GLUED = {"id": "codex-bad", "label": "bad", "harness": "codex", "flags": ["-cmcp_servers.e.command=sh"]}
MAIN = {"id": "claude-main", "label": "main", "harness": "claude", "default": True}


def _config(tmp_path: Path, profiles: List[Dict[str, Any]]) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({LAUNCH_PROFILES_KEY: {"revision": 3, "profiles": profiles}}))
    return path


def test_an_invalid_profile_is_set_aside_and_the_rest_load(tmp_path: Path) -> None:
    store = LaunchProfileStore(_config(tmp_path, [MAIN, GLUED]))
    with capture_logs() as logs:
        loaded = store.read_all()
    assert [p.id for p in loaded.block.profiles] == ["claude-main"]
    assert loaded.block.profiles[0].default is True and loaded.block.revision == 3
    [aside] = loaded.set_aside
    assert aside.id == "codex-bad" and "owned by the app or another field" in aside.reason
    assert aside.fallback_default is None
    assert any(e["event"] == "launch_profile_set_aside" and e["profile_id"] == "codex-bad"
               and "owned" in e["reason"] for e in logs)


def test_a_set_aside_default_falls_back_to_the_first_valid_profile(tmp_path: Path) -> None:
    spare = {"id": "codex-spare", "label": "spare", "harness": "codex"}
    store = LaunchProfileStore(_config(tmp_path, [MAIN, {**GLUED, "default": True}, spare]))
    loaded = store.read_all()
    assert {p.id: p.default for p in loaded.block.profiles} == {"claude-main": True, "codex-spare": True}
    assert loaded.set_aside[0].was_default is True and loaded.set_aside[0].fallback_default == "codex-spare"


def test_a_write_keeps_the_set_aside_profile_on_disk(tmp_path: Path) -> None:
    path = _config(tmp_path, [MAIN, GLUED])
    LaunchProfileStore(path).put(LaunchProfile.model_validate({"id": "claude-new", "label": "n", "harness": "claude"}))
    stored = json.loads(path.read_text())[LAUNCH_PROFILES_KEY]["profiles"]
    assert GLUED in stored and [p["id"] for p in stored] == ["claude-main", "claude-new", "codex-bad"]


def test_a_set_aside_profile_can_be_deleted(tmp_path: Path) -> None:
    path = _config(tmp_path, [MAIN, GLUED])
    LaunchProfileStore(path).delete("codex-bad")
    assert [p["id"] for p in json.loads(path.read_text())[LAUNCH_PROFILES_KEY]["profiles"]] == ["claude-main"]


def test_launches_resolve_from_the_valid_profiles(tmp_path: Path) -> None:
    block, _agents = _launch_view({LAUNCH_PROFILES_KEY: {"revision": 3, "profiles": [MAIN, GLUED]}})
    assert [p.id for p in block.profiles] == ["claude-main"]


def test_writing_an_invalid_profile_is_still_refused() -> None:
    with pytest.raises(ValueError, match="owned by the app or another field"):
        LaunchProfile.model_validate(GLUED)


def test_the_list_route_shows_the_disabled_profile_and_keeps_the_rest(env: Any) -> None:  # noqa: F811
    def add_bad(doc: Dict[str, Any]) -> Dict[str, Any]:
        block = doc[LAUNCH_PROFILES_KEY]
        return {**doc, LAUNCH_PROFILES_KEY: {**block, "profiles": [*block["profiles"], GLUED]}}

    config_writer.commit(env.config, add_bad)
    out = env.client.get("/api/v1/launch-profiles").json()
    assert "claude-main" in [p["id"] for p in out["profiles"]]
    assert next(p for p in out["profiles"] if p["id"] == "claude-main")["default"] is True
    [disabled] = out["disabled"]
    assert disabled["id"] == "codex-bad" and "owned by the app or another field" in disabled["reason"]
