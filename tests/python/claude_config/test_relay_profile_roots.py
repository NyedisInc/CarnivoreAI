
from __future__ import annotations

import json
from pathlib import Path

from src.core.claude_config import profile_roots


def test_relay_profile_sessions_root_is_listed(tmp_path, monkeypatch):
    relay = tmp_path / ".carnivore" / "accounts" / "0123456789ab-larkspur-relay"
    (relay / "sessions").mkdir(parents=True)
    (tmp_path / ".carnivore" / "accounts" / "plain-account" / "sessions").mkdir(parents=True)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({}))
    monkeypatch.delenv(profile_roots.ACCOUNTS_DIR_ENV)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    profile_roots.reset_profile_roots_cache_for_tests()
    roots = profile_roots.profile_subdir_roots(tmp_path / ".claude" / "sessions", "sessions", config)
    profile_roots.reset_profile_roots_cache_for_tests()
    assert roots == (tmp_path / ".claude" / "sessions", relay / "sessions")
