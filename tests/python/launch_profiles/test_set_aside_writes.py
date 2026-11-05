
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from structlog.testing import capture_logs

from src.config import wrappers
from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfile, LaunchProfilesConfig
from src.core import wrapper_store
from src.core.launch_profiles.bundle_guard import block_digest, merge_block, review
from src.core.launch_profiles.store import LaunchProfileStore

GLUED = {"id": "codex-bad", "label": "bad", "harness": "codex", "flags": ["-cmcp_servers.e.command=sh"]}
MAIN = {"id": "claude-main", "label": "main", "harness": "claude", "default": True}
SPARE = {"id": "claude-spare", "label": "spare", "harness": "claude"}


def _config(tmp_path: Path, profiles: List[Dict[str, Any]]) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({LAUNCH_PROFILES_KEY: {"revision": 1, "profiles": profiles}}))
    return path


def _stored(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text())[LAUNCH_PROFILES_KEY]["profiles"]


def test_a_saved_stand_in_default_leaves_one_default_after_a_repair(tmp_path: Path) -> None:
    spare = {"id": "codex-spare", "label": "spare", "harness": "codex"}
    path = _config(tmp_path, [MAIN, {**GLUED, "default": True}, spare])
    LaunchProfileStore(path).put(LaunchProfile.model_validate({"id": "claude-new", "label": "n", "harness": "claude"}))

    stored = _stored(path)
    repaired = [{**p, "flags": []} if p["id"] == "codex-bad" else p for p in stored]
    block = LaunchProfilesConfig.model_validate({"revision": 9, "profiles": repaired})
    assert [p.id for p in block.profiles if p.harness == "codex" and p.default] == ["codex-spare"]


def test_a_wrapper_delete_works_and_keeps_the_set_aside_entry(tmp_path: Path) -> None:
    path = _config(tmp_path, [MAIN, SPARE, GLUED])
    wrappers.mutate(path, lambda ws: wrapper_store.delete(ws, "claude-spare"))
    ids = [p["id"] for p in _stored(path)]
    assert "claude-spare" not in ids and "claude-main" in ids
    assert GLUED in _stored(path)


def test_a_wrapper_edit_works_and_keeps_the_set_aside_entry(tmp_path: Path) -> None:
    path = _config(tmp_path, [MAIN, GLUED])
    wrappers.mutate(path, lambda ws: wrapper_store.set_icon(ws, "claude-main", None))
    assert GLUED in _stored(path)


def test_a_bundle_merge_with_a_stand_in_default_repairs_to_one_default() -> None:
    spare = {"id": "codex-spare", "label": "spare", "harness": "codex"}
    existing = {"revision": 1, "profiles": [MAIN, {**GLUED, "default": True}, spare]}
    incoming = {"revision": 1, "profiles": [{"id": "claude-new", "label": "n", "harness": "claude"}]}
    merged = merge_block(existing, incoming)
    repaired = [{**p, "flags": []} if p["id"] == "codex-bad" else p for p in merged["profiles"]]
    block = LaunchProfilesConfig.model_validate({"revision": 9, "profiles": repaired})
    assert [p.id for p in block.profiles if p.harness == "codex" and p.default] == ["codex-spare"]


def test_a_wrapper_write_warns_once_about_the_set_aside_profile(tmp_path: Path) -> None:
    path = _config(tmp_path, [MAIN, GLUED])
    with capture_logs() as logs:
        wrappers.mutate(path, lambda ws: wrapper_store.set_icon(ws, "claude-main", None))
    assert [e["profile_id"] for e in logs if e["event"] == "launch_profile_set_aside"] == ["codex-bad"]


def test_a_set_aside_load_keeps_the_approved_resume_prefixes(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({LAUNCH_PROFILES_KEY: {
        "revision": 1, "profiles": [MAIN, GLUED], "approved_resume_prefixes": ["aider"]}}))
    assert LaunchProfileStore(path).read().approved_resume_prefixes == ["aider"]
    LaunchProfileStore(path).put(LaunchProfile.model_validate({"id": "claude-new", "label": "n", "harness": "claude"}))
    assert json.loads(path.read_text())[LAUNCH_PROFILES_KEY]["approved_resume_prefixes"] == ["aider"]


def test_a_resume_command_is_shown_and_bound_into_the_digest() -> None:
    base = {"id": "aider-x", "label": "a", "harness": "custom", "custom_command": {"script": 'aider "$@"'},
            "agent": {"resume": "aider --resume {id}"}}
    block = {"profiles": [base]}
    changed = {"profiles": [{**base, "agent": {"resume": "aider --other {id}"}}]}
    [row] = review(block)
    assert row["resume_command"] is True
    assert {"kind": "resume_command", "text": "aider --resume {id}"} in row["parts"]
    assert block_digest(block) != block_digest(changed)


def test_a_bundle_merge_carries_every_local_block_field(monkeypatch: Any) -> None:
    from src.config import launch_profiles_lenient
    from src.core.launch_profiles import bundle_guard

    class WithNote(LaunchProfilesConfig):

        note: str = ""

    monkeypatch.setattr(launch_profiles_lenient, "LaunchProfilesConfig", WithNote)
    monkeypatch.setattr(bundle_guard, "LaunchProfilesConfig", WithNote)
    existing = {"revision": 1, "profiles": [MAIN], "note": "local"}
    incoming = {"revision": 1, "profiles": [{"id": "claude-new", "label": "n", "harness": "claude"}]}
    assert merge_block(existing, incoming)["note"] == "local"
