
from __future__ import annotations

import pytest

from src.cplugs.save.service import RUNTIME
from tests.python.cplugs.folder_plugin_fixture import install_into_ship_list
from src.cplugs.sdk import transcript_files as tf, vault_sources


@pytest.fixture(autouse=True)
def isolated_world(monkeypatch, tmp_path):
    monkeypatch.setattr(tf, "config_file", lambda: tmp_path / "no-config.json")
    monkeypatch.setattr(vault_sources, "claude_roots", lambda: (tmp_path / "no-claude" / "projects",))
    monkeypatch.setattr(vault_sources, "codex_home", lambda: tmp_path / "no-codex")
    install_into_ship_list(monkeypatch)
    RUNTIME.reset()
    yield
    RUNTIME.reset()
