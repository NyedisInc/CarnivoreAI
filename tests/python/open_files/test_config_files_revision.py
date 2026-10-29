
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import config_files_routes
from src.api.auth import require_auth
from src.core import config_files

API = "/api/v1/config-files"


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    home = tmp_path / "claude-home"
    home.mkdir()
    monkeypatch.setattr(config_files, "CLAUDE_HOME", home)
    app = FastAPI()
    app.include_router(config_files_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def _params(project: Path) -> dict:
    return {"root": "workdir", "path": "a.txt", "project_path": str(project)}


def test_read_answers_the_revision_and_a_stale_write_is_refused(client, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("one\n")
    read = client.get(f"{API}/read", params=_params(project)).json()
    assert read["sha256"] == hashlib.sha256(b"one\n").hexdigest() and read["mtime_ns"] > 0
    (project / "a.txt").write_text("two\n")
    body = {**_params(project), "content": "mine\n", "expected_sha256": read["sha256"]}
    stale = client.post(f"{API}/write", json=body)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "file_changed_on_disk"
    assert (project / "a.txt").read_text() == "two\n"
    fresh = client.post(f"{API}/write", json={**body, "expected_sha256": stale.json()["detail"]["sha256"]})
    assert fresh.status_code == 200 and fresh.json()["sha256"] == hashlib.sha256(b"mine\n").hexdigest()


def test_a_write_naming_no_base_still_lands(client, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("one\n")
    landed = client.post(f"{API}/write", json={**_params(project), "content": "two\n"})
    assert landed.status_code == 200 and (project / "a.txt").read_text() == "two\n"


def test_two_saves_on_the_same_revision_never_both_land(tmp_path, monkeypatch):
    import threading
    import time

    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("one\n")
    base = hashlib.sha256(b"one\n").hexdigest()
    real_write = config_files.atomic_write

    def slow_write(path, content, mode=None):
        time.sleep(0.2)
        real_write(path, content, mode=mode)

    monkeypatch.setattr(config_files, "atomic_write", slow_write)
    outcomes: list[str] = []
    start = threading.Barrier(2)

    def save(text: str) -> None:
        start.wait()
        try:
            config_files.write_file("workdir", "a.txt", text, str(project), expected_sha256=base)
            outcomes.append("saved")
        except config_files.FileChangedOnDiskError:
            outcomes.append("stale")

    threads = [threading.Thread(target=save, args=(t,)) for t in ("phone\n", "desk\n")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert sorted(outcomes) == ["saved", "stale"]
    assert (project / "a.txt").read_text() in ("phone\n", "desk\n")


def test_a_file_that_cannot_be_read_is_unreadable_not_a_crash(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("one\n")

    def refuse(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    with pytest.raises(config_files.ConfigFileUnreadableError):
        config_files.read_file("workdir", "a.txt", str(project))


def test_a_save_that_landed_answers_no_revision_when_the_re_read_fails(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_text("one\n")
    calls = {"n": 0}
    real_revision = config_files.file_revision

    def failing_after_write(path):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError(11, "Resource deadlock avoided")
        return real_revision(path)

    monkeypatch.setattr(config_files, "file_revision", failing_after_write)
    result = config_files.write_file(
        "workdir", "a.txt", "two\n", str(project), expected_sha256=hashlib.sha256(b"one\n").hexdigest()
    )
    assert (project / "a.txt").read_text() == "two\n"
    assert result["sha256"] is None and result["mtime_ns"] is None
