
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.config.launch_profiles import LaunchProfile
from src.core.launch_profiles.bundle_guard import block_digest
from src.core.launch_profiles.share import executable_parts
from tests.python.config_bundle.test_bundle_command_consent import IMPORT, _pair


def _profile_rows(client: Any, bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    preview = client.post(IMPORT, json={"bundle": bundle}).json()
    assert preview["contains_commands"] is True
    return preview["launch_profiles"]["profiles"]


def _set_local_profiles(cfg: Path, profiles: List[Dict[str, Any]]) -> None:
    doc = json.loads(cfg.read_text())
    doc["launch_profiles"] = {"revision": 1, "profiles": profiles}
    cfg.write_text(json.dumps(doc))


def _make(**fields: Any) -> LaunchProfile:
    return LaunchProfile.model_validate({"id": "p-1", "label": "p", "harness": "claude", **fields})


def test_a_skip_all_profile_shows_its_permissions_on_the_consent_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, client, _cfg = _pair(tmp_path, monkeypatch)
    bundle["config"]["launch_profiles"] = {"revision": 1, "profiles": [
        {"id": "claude-quiet", "label": "quiet", "harness": "claude", "permissions": "skip_all"}]}

    parts = _profile_rows(client, bundle)[0]["parts"]
    assert {"kind": "permissions", "value": "skip_all", "text": "--dangerously-skip-permissions",
            "tone": "danger"} in parts


def test_a_change_to_skip_all_on_the_default_profile_shows_old_value_and_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, client, cfg = _pair(tmp_path, monkeypatch)
    _set_local_profiles(cfg, [{"id": "claude-main", "label": "main", "harness": "claude", "default": True}])
    bundle["config"]["launch_profiles"] = {"revision": 1, "profiles": [
        {"id": "claude-main", "label": "main", "harness": "claude", "permissions": "skip_all"}]}

    parts = _profile_rows(client, bundle)[0]["parts"]
    assert {"kind": "permissions", "value": "skip_all", "text": "--dangerously-skip-permissions",
            "was": "harness_default", "was_text": "", "tone": "danger"} in parts
    assert {"kind": "default", "value": "kept", "text": "claude-main"} in parts


def test_an_endpoint_connection_is_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, client, _cfg = _pair(tmp_path, monkeypatch)
    bundle["config"]["launch_profiles"] = {"revision": 1, "profiles": [
        {"id": "claude-proxy", "label": "proxy", "harness": "claude",
         "endpoint": {"mode": "connection", "connection_id": "conn-x"}}]}

    parts = _profile_rows(client, bundle)[0]["parts"]
    assert {"kind": "endpoint", "value": "connection", "text": "conn-x"} in parts


def test_a_plain_profile_shows_only_its_harness() -> None:
    assert executable_parts(_make()) == [{"kind": "harness", "value": "claude", "text": ""}]


def test_lowering_permissions_still_shows_what_it_was() -> None:
    old = _make(harness="codex", permissions="skip_all")
    new = old.model_copy(update={"permissions": "harness_default"})
    assert {"kind": "permissions", "value": "harness_default", "text": "", "was": "skip_all",
            "was_text": "--yolo"} in executable_parts(new, existing=old)


def test_a_harness_switch_is_shown_with_what_it_was() -> None:
    old = _make()
    new = _make(harness="shell")
    assert {"kind": "harness", "value": "shell", "text": "", "was": "claude", "was_text": ""} in executable_parts(
        new, existing=old)


def test_the_local_default_is_part_of_the_bundle_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    block = {"profiles": [{"id": "claude-main", "label": "main", "harness": "claude", "permissions": "skip_all"}]}
    plain = {"profiles": [{"id": "claude-main", "label": "main", "harness": "claude"}]}
    default = {"profiles": [{"id": "claude-main", "label": "main", "harness": "claude", "default": True}]}
    assert block_digest(block, plain) != block_digest(block, default)

    bundle, client, cfg = _pair(tmp_path, monkeypatch)
    _set_local_profiles(cfg, plain["profiles"])
    bundle["config"]["launch_profiles"] = {"revision": 1, **block}
    seen = client.post(IMPORT, json={"bundle": bundle}).json()["launch_profiles"]["sha256"]
    _set_local_profiles(cfg, default["profiles"])
    stale = client.post(IMPORT, json={"bundle": bundle, "dry_run": False, "confirm_launch_profiles_sha256": seen})
    assert stale.status_code == 409, stale.text
