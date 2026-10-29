
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.core.attention import registry_read
from src.core.claude_config import profile_roots


@pytest.fixture()
def two_profiles(tmp_path, monkeypatch):
    default = tmp_path / "home" / ".claude" / "sessions"
    default.mkdir(parents=True)
    profile = tmp_path / "accounts" / "work"
    (profile / "sessions").mkdir(parents=True)
    pid = os.getpid()
    (profile / "sessions" / f"{pid}.json").write_text(json.dumps(
        {"pid": pid, "status": "idle", "tmux": "cloude_managed:@1.%1",
         "sessionId": "33333333-aaaa-bbbb-cccc-000000000003"}))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"provider_accounts": {"accounts": [
        {"id": "work", "name": "work", "provider": "claude",
         "claude_config_dir": str(profile)}]}}))
    monkeypatch.setattr(registry_read, "default_registry_directory", lambda: str(default))
    monkeypatch.setattr(profile_roots, "_default_config_path", lambda: config)
    profile_roots.reset_profile_roots_cache_for_tests()
    yield {"default": default, "profile": profile, "config": config, "pid": pid}
    profile_roots.reset_profile_roots_cache_for_tests()


def test_registry_index_finds_a_record_only_under_the_managed_profile(two_profiles):
    index = registry_read.read_registry_index()
    record = index["cloude_managed"]
    assert record.verdict == registry_read.REG_OK
    assert record.session_uuid == "33333333-aaaa-bbbb-cccc-000000000003"


def test_an_explicit_directory_reads_only_that_directory(two_profiles):
    assert dict(registry_read.read_registry_index(str(two_profiles["default"]))) == {}


def test_registry_file_path_names_the_profile_file(two_profiles):
    path = profile_roots.registry_file_path(two_profiles["pid"])
    assert path == str(two_profiles["profile"] / "sessions" / f"{two_profiles['pid']}.json")


def test_symlinked_profile_sessions_is_one_root(tmp_path, monkeypatch):
    default = tmp_path / "home" / ".claude" / "sessions"
    default.mkdir(parents=True)
    profile = tmp_path / "accounts" / "linked"
    profile.mkdir(parents=True)
    (profile / "sessions").symlink_to(default)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"provider_accounts": {"accounts": [
        {"id": "linked", "name": "linked", "provider": "claude",
         "claude_config_dir": str(profile)}]}}))
    monkeypatch.setattr(registry_read, "default_registry_directory", lambda: str(default))
    profile_roots.reset_profile_roots_cache_for_tests()
    assert profile_roots.claude_registry_roots(config) == (default,)
    profile_roots.reset_profile_roots_cache_for_tests()


def test_nothing_outside_sessions_and_projects_can_be_asked_for(two_profiles):
    profile = two_profiles["profile"]
    (profile / ".credentials.json").write_text("{}")
    (profile / "auth").mkdir()
    for forbidden in (".credentials.json", "auth", "keychain", ".."):
        with pytest.raises(profile_roots.ForbiddenSubdirError):
            profile_roots.profile_subdir_roots(Path("/x"), forbidden, two_profiles["config"])
    assert profile_roots.ALLOWED_SUBDIRS == {"sessions", "projects"}
    roots = {str(r) for r in profile_roots.claude_registry_roots(two_profiles["config"])}
    assert all(r.endswith("/sessions") for r in roots)
