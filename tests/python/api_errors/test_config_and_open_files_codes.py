
from __future__ import annotations

from src.api import config_routes
from src.core import config_files
from src.core.app_config_guard import APP_CONFIG_PROTECTED, AppConfigProtectedError

from .conftest import LEAK, assert_fixed

BODY = {"root": "user", "path": "a.md", "content": "x"}


def test_a_stale_config_file_save_keeps_the_sha_key(driver, monkeypatch):
    def stale(**_k):
        raise config_files.FileChangedOnDiskError("abc123")

    monkeypatch.setattr(config_files, "write_file", stale)
    response, events = driver.call("POST", "/config-files/write", None, json=BODY)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "file_changed_on_disk" and detail["sha256"] == "abc123"
    assert any(e.get("code") == "file_changed_on_disk" for e in events)


def test_the_protected_app_config_answers_a_code_without_the_text(driver, monkeypatch):
    def protected(**_k):
        raise AppConfigProtectedError(f"{LEAK} is the app config")

    monkeypatch.setattr(config_files, "write_file", protected)
    response, events = driver.call("POST", "/config-files/write", None, json=BODY)
    assert_fixed(response, 409, APP_CONFIG_PROTECTED, events)


def test_a_stale_favorites_write_keeps_the_current_row(monkeypatch, tmp_path):
    monkeypatch.setattr(config_routes.slash_favorites, "payload", lambda _p: {"favorites": ["/clear"]})
    caught = config_routes._stale_conflict(tmp_path / "config.json", ValueError(f"stale {LEAK}"))
    assert caught.status_code == 409 and caught.detail["code"] == "favorites_stale"
    assert caught.detail["current"] == {"favorites": ["/clear"]} and LEAK not in str(caught.detail)
