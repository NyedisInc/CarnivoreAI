
from __future__ import annotations

from pathlib import Path

from .conftest import LEAK


def _fixed(response, status: int, code: str, events: list) -> None:
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code and LEAK not in response.text
    assert any(e.get("event") == "api_request_failed" and e.get("code") == code for e in events)


def test_browse_a_folder_that_fails_to_list_answers_a_code(driver, monkeypatch, tmp_path):
    def boom(self):
        raise OSError(f"EIO {LEAK}")

    monkeypatch.setattr(Path, "iterdir", boom)
    response, events = driver.call("GET", f"/filesystem/browse?path={tmp_path}", None)
    _fixed(response, 500, "directory_unreadable", events)
    assert any(LEAK in str(e.get("error")) for e in events if e.get("code") == "directory_unreadable")


def test_mkdir_failure_answers_a_code(driver, monkeypatch, tmp_path):
    def boom(self, *a, **k):
        raise OSError(f"EACCES {LEAK}")

    monkeypatch.setattr(Path, "mkdir", boom)
    response, events = driver.call("POST", "/filesystem/mkdir", None, json={"path": str(tmp_path / "new")})
    _fixed(response, 400, "directory_create_failed", events)
