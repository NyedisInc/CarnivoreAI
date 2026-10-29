import os

import pytest

from src.core.swarm import create, project_agent  # noqa: F401


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return os.path.realpath(home)


def _mk(home, *parts):
    path = os.path.join(home, *parts)
    os.makedirs(path, exist_ok=True)
    return path


@pytest.mark.parametrize("parts", [
    ("Library", "Mobile Documents", "com~apple~CloudDocs", "x"),
    ("Library", "Mobile Documents", "com~apple~CloudDocs", "Sync", "x"),
    ("Library", "CloudStorage", "GoogleDrive-a@b.c", "x"),
])
def test_user_content_is_not_a_system_folder(fake_home, parts):
    refusal = project_agent._git_init_refusal(_mk(fake_home, *parts))
    assert not refusal or "system folder" not in refusal


@pytest.mark.parametrize("parts", [
    ("Library", "Preferences", "x"),
    ("Library", "Mobile Documents"),
    ("Library", "Mobile Documents", "com~apple~CloudDocs"),
    ("Library", "CloudStorage"),
    ("Library", "CloudStorage", "GoogleDrive-a@b.c"),
    ("Library",),
])
def test_other_library_folders_stay_refused(fake_home, parts):
    assert "system folder" in project_agent._git_init_refusal(_mk(fake_home, *parts))
