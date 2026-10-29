
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from src.core.claude_config import profile_roots


def test_every_transcript_root_resolves_inside_the_temp_dir(tmp_path, monkeypatch):
    accounts = Path(os.environ[profile_roots.ACCOUNTS_DIR_ENV])
    assert accounts.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    relay = accounts / "0123456789ab-x-relay"
    (relay / "projects").mkdir(parents=True)
    try:
        config = tmp_path / "config.json"
        config.write_text("{}")
        monkeypatch.setattr(profile_roots, "_default_config_path", lambda: config)
        profile_roots.reset_profile_roots_cache_for_tests()
        roots = profile_roots.profile_subdir_roots(
            tmp_path / "projects", profile_roots.PROJECTS_DIRNAME
        )[1:]
        assert roots == (relay / "projects",)
        for root in roots:
            assert Path(root).resolve().is_relative_to(accounts.resolve())
    finally:
        profile_roots.reset_profile_roots_cache_for_tests()
        (relay / "projects").rmdir()
        relay.rmdir()
