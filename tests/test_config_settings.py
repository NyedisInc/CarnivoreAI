from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cs_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cs_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.auth_routes import router as auth_router
from src.config import settings


BASE_CONFIG = {
    "projects": [],
    "agents": {
        "claude_command": "",
        "codex_command": "codex",
        "hermes_command": "hermes",
        "openclaw_command": "openclaw tui",
    },
    "notifications": {
        "enabled": True,
        "ntfy_base_url": "https://ntfy.sh",
        "ntfy_topic": "topic-secret-abc",
        "slack_webhook_url": "https://hooks.slack.com/services/T/B/X",
        "pushover_token": "tok123",
        "pushover_user_key": "userkey456",
    },
}


def _write_config(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


@pytest.fixture()
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    _write_config(path, BASE_CONFIG)
    monkeypatch.setattr(settings, "auth_config_file", str(path))
    settings._auth_config_cache = None
    yield path
    settings._auth_config_cache = None


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)




def test_get_settings_has_no_notifications_block_and_echoes_no_legacy_secret(client, config_path):
    resp = client.get("/api/v1/config/settings")
    assert resp.status_code == 200, resp.text
    assert "topic-secret-abc" in config_path.read_text()
    for secret in ("topic-secret-abc", "T/B/X", "tok123", "userkey456"):
        assert secret not in resp.text
    assert "notifications" not in resp.json()


def test_get_settings_agents_carries_wrappers_and_families_only(client, config_path):
    resp = client.get("/api/v1/config/settings")
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert set(agents) == {"wrappers", "families"}
    codex = next(f for f in agents["families"] if f["name"] == "codex")
    assert 'codex "$@"' in codex["effective_command"]
    assert "command_field" not in codex and "in_use" not in codex


def test_get_settings_server_section_is_read_only(client, config_path):
    resp = client.get("/api/v1/config/settings")
    assert resp.status_code == 200
    server = resp.json()["server"]
    assert server["editable"] is False
    assert "host" in server




@pytest.mark.parametrize("agents", [
    {"claude_command": "claude --dangerously-skip-permissions"},
    {"codex_command": "codex --yolo"},
    {"claude_command": ""},
])
def test_patch_agents_is_refused_and_writes_nothing(client, config_path, agents):
    before = config_path.read_text()
    resp = client.patch("/api/v1/config/settings", json={"agents": agents})
    assert resp.status_code == 422
    assert config_path.read_text() == before




def test_patch_notifications_is_refused_and_leaves_the_file_untouched(client, config_path):
    before = config_path.read_text()
    resp = client.patch(
        "/api/v1/config/settings",
        json={"notifications": {"ntfy_base_url": "https://ntfy.example.com"}},
    )
    assert resp.status_code == 422
    assert config_path.read_text() == before


def test_a_patch_to_another_block_leaves_a_legacy_notifications_block_byte_for_byte(client, config_path):
    resp = client.patch("/api/v1/config/settings", json={"workspace": {"default_shell": "/bin/zsh"}})
    assert resp.status_code == 200, resp.text
    on_disk = json.loads(config_path.read_text())
    assert on_disk["notifications"] == BASE_CONFIG["notifications"]
    assert on_disk["workspace"]["default_shell"] == "/bin/zsh"
    assert "topic-secret-abc" not in resp.text




def test_patch_rejects_unknown_top_level_key(client, config_path):
    resp = client.patch(
        "/api/v1/config/settings",
        json={"host": "0.0.0.0"},
    )
    assert resp.status_code == 422
    on_disk = json.loads(config_path.read_text())
    assert on_disk == BASE_CONFIG


def test_patch_rejects_unknown_nested_key(client, config_path):
    resp = client.patch(
        "/api/v1/config/settings",
        json={"workspace": {"default_shell": "/bin/zsh", "sudo_command": "rm -rf /"}},
    )
    assert resp.status_code == 422
    on_disk = json.loads(config_path.read_text())
    assert "workspace" not in on_disk


def test_patch_empty_body_is_a_harmless_noop(client, config_path):
    resp = client.patch("/api/v1/config/settings", json={})
    assert resp.status_code == 200, resp.text
    on_disk = json.loads(config_path.read_text())
    assert on_disk == BASE_CONFIG




def test_patch_writes_backup_of_prior_content(client, config_path):
    before = config_path.read_text()
    resp = client.patch(
        "/api/v1/config/settings",
        json={"workspace": {"default_shell": "/bin/zsh"}},
    )
    assert resp.status_code == 200, resp.text

    backup_path = config_path.with_suffix(config_path.suffix + ".bak")
    assert backup_path.exists()
    assert backup_path.read_text() == before


def test_patch_leaves_no_stray_tmp_file(client, config_path):
    resp = client.patch(
        "/api/v1/config/settings",
        json={"workspace": {"default_shell": "/bin/zsh"}},
    )
    assert resp.status_code == 200, resp.text
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    assert not tmp_path.exists()


def test_patch_result_is_valid_json_at_every_step(client, config_path):
    resp = client.patch(
        "/api/v1/config/settings",
        json={"workspace": {"default_shell": "/bin/bash"}},
    )
    assert resp.status_code == 200, resp.text
    json.loads(config_path.read_text())




def test_a_write_that_fails_part_way_leaves_config_json_intact(
    config_path, monkeypatch
):
    import json as _json

    from src.core import config_writer

    before = config_path.read_text()

    def _dump_then_die(obj, fp, **kwargs):
        fp.write('{"agents": {"claude_comm')
        raise OSError("no space left on device")

    monkeypatch.setattr(config_writer.json, "dump", _dump_then_die)

    with pytest.raises(OSError):
        config_writer.commit(
            config_path,
            lambda data: {**data, "agents": {"claude_command": "new"}},
        )

    assert config_path.read_text() == before, (
        "a write that failed part way through changed config.json; the "
        "destination must only ever be replaced by a completed rename"
    )
    assert _json.loads(config_path.read_text())


def test_the_destination_is_reached_by_a_rename_and_not_by_a_write(
    config_path, monkeypatch
):
    from src.core import config_writer

    real_open = open
    opened_for_write = []

    def _tracking_open(file, mode="r", *args, **kwargs):
        if "w" in mode or "a" in mode or "+" in mode:
            opened_for_write.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(config_writer, "open", _tracking_open, raising=False)

    real_os_open = os.open

    def _tracking_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT):
            opened_for_write.append(str(path))
        return real_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", _tracking_os_open)

    config_writer.commit(
        config_path,
        lambda data: {**data, "agents": {"claude_command": "renamed-in"}},
    )

    assert str(config_path) not in opened_for_write, (
        "config.json itself was opened for writing; the destination must "
        f"only be reached by os.replace. Opened: {opened_for_write}"
    )
    assert any(p.endswith(".tmp") for p in opened_for_write), (
        "nothing was written through a temp file at all"
    )




def test_a_save_is_visible_through_an_already_warm_cache(client, config_path):
    from src.config import settings as live_settings

    assert live_settings.load_auth_config().workspace.default_shell != "/bin/bash"
    assert live_settings._auth_config_cache is not None

    resp = client.patch(
        "/api/v1/config/settings",
        json={"workspace": {"default_shell": "/bin/bash"}},
    )
    assert resp.status_code == 200, resp.text

    assert resp.json()["workspace"]["default_shell"] == "/bin/bash", (
        "the response carried the pre-write value; the cached config was "
        "not invalidated by the write"
    )
    assert live_settings.load_auth_config().workspace.default_shell == "/bin/bash"


def test_a_merge_that_would_not_validate_never_reaches_disk(config_path):
    from src.config import config_writes

    before = config_path.read_text()

    with pytest.raises(ValueError):
        config_writes.update_settings_config(
            config_path,
            workspace_update={"env": "not-a-map-at-all"},
        )

    assert config_path.read_text() == before, (
        "a merged block that pydantic refuses was written to disk"
    )
