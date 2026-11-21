
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.api import project_clone_routes
from tests.python.route_tests.harness import add_projects, client_for, point_state_at


class _FakeProc:

    def __init__(self, returncode: int = 0, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self._stderr


def _fake_gh(monkeypatch: pytest.MonkeyPatch, clone_rc: int = 0, stderr: bytes = b"") -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    async def spawn(*argv: Any, **_kw: Any) -> _FakeProc:
        calls.append(argv)
        if argv[:3] == ("gh", "repo", "clone"):
            if clone_rc == 0:
                Path(argv[4]).mkdir(parents=True)
            return _FakeProc(clone_rc, stderr)
        return _FakeProc(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return point_state_at(tmp_path, monkeypatch)


def test_clone_registers_the_project_under_parent_slash_repo(state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_gh(monkeypatch)
    parent = tmp_path / "work"
    resp = client_for(project_clone_routes.router).post(
        "/projects/clone", json={"repo_url": "https://github.com/acme/widgets.git", "parent_dir": str(parent)}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "widgets"
    assert Path(body["path"]).resolve() == (parent / "widgets").resolve()
    clone = [c for c in calls if c[:3] == ("gh", "repo", "clone")][0]
    assert clone[3] == "https://github.com/acme/widgets.git"


def test_clone_refuses_an_unparseable_url_before_touching_disk(state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_gh(monkeypatch)
    parent = tmp_path / "never"
    resp = client_for(project_clone_routes.router).post(
        "/projects/clone", json={"repo_url": "justaname", "parent_dir": str(parent)}
    )
    assert resp.status_code == 400
    assert not [c for c in calls if c[:3] == ("gh", "repo", "clone")]
    assert not parent.exists()


def test_clone_refuses_when_the_target_folder_exists(state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_gh(monkeypatch)
    (tmp_path / "work" / "widgets").mkdir(parents=True)
    resp = client_for(project_clone_routes.router).post(
        "/projects/clone", json={"repo_url": "acme/widgets", "parent_dir": str(tmp_path / "work")}
    )
    assert resp.status_code == 409
    assert not [c for c in calls if c[:3] == ("gh", "repo", "clone")]


def test_clone_refuses_a_name_that_is_already_a_project(state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    add_projects(state, [("widgets", tmp_path / "elsewhere")])
    _fake_gh(monkeypatch)
    resp = client_for(project_clone_routes.router).post(
        "/projects/clone", json={"repo_url": "acme/widgets", "parent_dir": str(tmp_path / "work")}
    )
    assert resp.status_code == 409


@pytest.mark.parametrize(
    "stderr,status",
    [(b"authentication failed", 401), (b"repository not found", 404), (b"boom", 500)],
)
def test_clone_failure_maps_gh_stderr_to_a_typed_status(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stderr: bytes, status: int
) -> None:
    _fake_gh(monkeypatch, clone_rc=1, stderr=stderr)
    client = client_for(project_clone_routes.router)
    resp = client.post("/projects/clone", json={"repo_url": "acme/widgets", "parent_dir": str(tmp_path / "work")})
    assert resp.status_code == status
    assert not (tmp_path / "work" / "widgets").exists()


def test_clone_needs_auth(tmp_path: Path) -> None:
    resp = client_for(project_clone_routes.router, signed_in=False).post(
        "/projects/clone", json={"repo_url": "acme/widgets", "parent_dir": str(tmp_path / "x")}
    )
    assert resp.status_code in (401, 403)
