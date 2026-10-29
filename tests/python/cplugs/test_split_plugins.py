
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from src.cplugs.host import gate, runtime, state as owner_state
from src.cplugs.host.split_migration import effective_switches, migrate


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDE_SAVE_PIPELINE", raising=False)


def _config(tmp_path: Path, document: Dict[str, Any]) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _stored(state_dir: Path) -> Dict[str, Optional[bool]]:
    return {i: owner_state.stored_enabled(state_dir, i) for i in ("save",)}


def test_default_state_is_save_off(tmp_path: Path) -> None:
    for cplug_id, expected, asks in (("save", False, ("sessions.read", "sessions.create")),):
        manifest = runtime.find(cplug_id).manifest
        assert manifest.tier == "builtin" and manifest.permissions == asks
        assert owner_state.default_state(manifest).enabled is expected
        assert gate.is_on(cplug_id, tmp_path) is expected
    assert gate.is_on("no_such_plugin", tmp_path) is False


def test_the_owner_switch_overrides_the_default_and_the_gate_reads_it(tmp_path: Path) -> None:
    manifest = runtime.find("save").manifest
    owner_state.update(tmp_path, manifest, None, lambda st: replace(st, enabled=True))
    assert gate.is_on("save", tmp_path) is True
    assert owner_state.stored_enabled(tmp_path, "save") is True


def test_a_fresh_install_stores_save_off_and_an_existing_one_keeps_it_on(tmp_path: Path) -> None:
    fresh, upgraded = tmp_path / "fresh", tmp_path / "upgraded"
    fresh.mkdir()
    upgraded.mkdir()
    assert migrate(fresh, _config(fresh, {}), fresh_install=True) == {"save": False}
    assert migrate(upgraded, _config(upgraded, {}), fresh_install=False) == {"save": True}
    assert migrate(fresh, _config(fresh, {}), fresh_install=False) == {}
    assert owner_state.stored_enabled(fresh, "save") is False


def test_migration_keeps_an_install_that_ran_nothing_off(tmp_path: Path) -> None:
    config = _config(tmp_path, {})
    assert effective_switches(config) == {"save": True}
    assert migrate(tmp_path, config) == {"save": True}
    assert _stored(tmp_path) == {"save": True}


def test_a_stored_summarize_entry_from_the_killed_plugin_is_ignored_and_never_crashes(tmp_path: Path) -> None:
    state_file = tmp_path / "cplugs" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"summarize": {"enabled": True, "grants": [], "revision": 1}}))
    assert migrate(tmp_path, _config(tmp_path, {})) == {"save": True}
    assert gate.is_on("summarize", tmp_path) is False
    assert runtime.find("summarize") is None


def test_a_stored_backup_entry_from_the_retired_plugin_is_ignored_and_never_crashes(tmp_path: Path) -> None:
    state_file = tmp_path / "cplugs" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"backup": {"enabled": True, "grants": [], "revision": 1}}))
    config = _config(tmp_path, {"message_archive": {"enabled": True}})
    assert migrate(tmp_path, config) == {"save": True}
    assert gate.is_on("backup", tmp_path) is False
    assert runtime.find("backup") is None


def test_migration_runs_once_and_never_overrides_an_owner_choice(tmp_path: Path) -> None:
    config = _config(tmp_path, {})
    owner_state.update(tmp_path, runtime.find("save").manifest, None, lambda st: replace(st, enabled=False))
    assert migrate(tmp_path, config) == {}
    assert owner_state.stored_enabled(tmp_path, "save") is False
    assert migrate(tmp_path, config) == {}


OWNER_PRE_SPLIT_CONFIG = {
    "config_version": 8,
    "message_archive": {"enabled": False},
    "save_pipeline": {"capture_scope": "all"},
    "byoai": {
        "revision": 5,
        "connections": [
            {"id": "custom-0001", "preset": "custom", "label": "llm-a", "base_url": "http://127.0.0.1:1/v1",
             "options": {"protocol": "openai_chat", "capabilities": ["chat"], "auth": "none"}, "enabled": True},
            {"id": "ollama-0001", "preset": "ollama", "label": "llm-b", "base_url": "http://127.0.0.1:2", "enabled": True},
        ],
        "defaults": {},
        "features": {
            "pipeline.summary": {"connection": "custom-0001", "model": "model-a", "voice": None},
            "pipeline.summary.spill": {"connection": "ollama-0001", "model": "model-b", "voice": None},
        },
    },
}


def test_owners_pre_split_install_keeps_save_and_leaves_the_handoff_summary_and_retired_archive_off(tmp_path: Path) -> None:
    config = _config(tmp_path, OWNER_PRE_SPLIT_CONFIG)
    owner_state.update(tmp_path, runtime.find("huddle").manifest, None, lambda st: replace(st, enabled=True))
    assert migrate(tmp_path, config) == {"save": True}
    assert _stored(tmp_path) == {"save": True}
    assert owner_state.stored_enabled(tmp_path, "huddle") is True
