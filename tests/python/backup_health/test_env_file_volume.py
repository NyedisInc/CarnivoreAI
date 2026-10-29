
from __future__ import annotations

import os
from pathlib import Path

import pytest
import structlog

import src.config  # noqa: F401
from src.core.backup_health import checks

SECRET = "P18_PROBE_SECRET=hunter2-super-secret"
NAMES = ("CARNIVORE_BACKUP_VOLUME", "CLOUDE_BACKUP_VOLUME", "CLOUDECODE_BACKUP_VOLUME")


@pytest.fixture()
def envfile(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr("src.api.enrollment_routes.env_file_path", lambda: path)
    for n in NAMES:
        monkeypatch.delenv(n, raising=False)

    def write(text: str) -> Path:
        path.write_text(text)
        return path

    return write


def test_env_file_turns_the_check_on(envfile):
    envfile(f"{SECRET}\nCARNIVORE_BACKUP_VOLUME=/Volumes/Backup\n")
    assert checks.backup_volume() == Path("/Volumes/Backup")


def test_legacy_spellings_in_env_file(envfile):
    for name in ("CLOUDE_BACKUP_VOLUME", "CLOUDECODE_BACKUP_VOLUME"):
        envfile(f"{name}=/Volumes/Old\n")
        assert checks.backup_volume() == Path("/Volumes/Old")


def test_process_environment_wins(envfile, monkeypatch):
    envfile("CARNIVORE_BACKUP_VOLUME=/Volumes/FromFile\n")
    monkeypatch.setenv("CLOUDE_BACKUP_VOLUME", "/Volumes/FromEnv")
    assert checks.backup_volume() == Path("/Volumes/FromEnv")
    monkeypatch.setenv("CARNIVORE_BACKUP_VOLUME", "off")
    assert checks.backup_volume() is None
    monkeypatch.setenv("CARNIVORE_BACKUP_VOLUME", "")
    assert checks.backup_volume() is None


@pytest.mark.parametrize("value", ["off", "OFF", "", "   "])
def test_off_or_empty_in_env_file_is_off(envfile, value):
    envfile(f"CARNIVORE_BACKUP_VOLUME={value}\n")
    assert checks.backup_volume() is None


def test_missing_or_unreadable_env_file_is_off_and_logs_no_contents(envfile, tmp_path):
    path = envfile(SECRET + "\n")
    path.unlink()
    assert checks.backup_volume() is None
    path.write_bytes(b"\xff\xfe" + SECRET.encode() + b"\n")
    with structlog.testing.capture_logs() as logs:
        assert checks.backup_volume() is None
    assert "hunter2" not in repr(logs)


def test_unrelated_secret_never_escapes(envfile):
    envfile(f"{SECRET}\nCARNIVORE_BACKUP_VOLUME=/Volumes/Backup\n")
    checks.backup_volume()
    before = dict(os.environ)
    with structlog.testing.capture_logs() as logs:
        result = checks.backup_volume()
    assert "hunter2" not in repr(result) + repr(logs)
    assert dict(os.environ) == before and "P18_PROBE_SECRET" not in os.environ


def test_reference_in_env_value_is_taken_literally(envfile, monkeypatch):
    monkeypatch.setenv("P18_HOST_SECRET", "FAKE_TOKEN_c0ffee1234")
    envfile("P18_OTHER=FAKE_OTHER_beef\nCARNIVORE_BACKUP_VOLUME=/Volumes/${P18_OTHER}${P18_HOST_SECRET}\n")
    got = str(checks.backup_volume())
    assert "FAKE_OTHER_beef" not in got and "FAKE_TOKEN_c0ffee1234" not in got
    assert got == "/Volumes/${P18_OTHER}${P18_HOST_SECRET}"


def test_lowercase_key_in_env_file_is_read(envfile):
    envfile("carnivore_backup_volume=/Volumes/Backup\n")
    assert checks.backup_volume() == Path("/Volumes/Backup")
