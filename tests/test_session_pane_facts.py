
from __future__ import annotations

import subprocess
import uuid
from typing import Optional

import pytest

from src.core.session_pane_facts import display_path, git_branch, parse_display
from src.core.tmux_discovery import tmux_argv_prefix
from tests.socket_guard import TEST_SOCKET_NAME


class _Info:

    def __init__(self, tmux_name: Optional[str]) -> None:
        self.tmux_session = tmux_name


class _Manager:

    def __init__(self, rows: dict) -> None:
        self._rows = rows

    async def get_session_info(self, session_id: Optional[str] = None):
        return self._rows.get(session_id)

    def _tmux_socket_name(self) -> str:
        return TEST_SOCKET_NAME


def _client(rows: dict):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = _Manager(rows)
    return TestClient(app)


def _repo(root, branch: str):
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    sub = root / "src" / "deep"
    sub.mkdir(parents=True)
    return sub


def test_git_branch_reads_head_walking_up(tmp_path):
    sub = _repo(tmp_path, "feat/x")
    assert git_branch(str(sub)) == "feat/x"


def test_git_branch_follows_a_worktree_gitdir_file_and_detached_head(tmp_path):
    gitdir = tmp_path / "gd"
    gitdir.mkdir()
    (gitdir / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {gitdir}\n")
    assert git_branch(str(wt)) == "0123456"


def test_git_branch_is_none_outside_a_repository(tmp_path):
    assert git_branch(str(tmp_path)) is None


def test_display_path_writes_home_as_tilde():
    assert display_path("/Users/a/x", "/Users/a") == "~/x"
    assert display_path("/Users/a", "/Users/a") == "~"
    assert display_path("/Users/ab/x", "/Users/a") == "/Users/ab/x"


def test_parse_display_refuses_a_line_about_another_session():
    assert parse_display("\n", "s").cwd is None
    assert parse_display("other\t/tmp\tzsh\t80\t24\n", "s").cwd is None
    facts = parse_display("s\t/tmp\tzsh\t80\t24\n", "s")
    assert (facts.cwd, facts.command, facts.cols, facts.rows) == ("/tmp", "zsh", 80, 24)


@pytest.mark.real_tmux
def test_route_reads_a_live_pane(tmp_path):
    sub = _repo(tmp_path, "main")
    name = f"cloude_pf_{uuid.uuid4().hex[:8]}"
    prefix = tmux_argv_prefix(TEST_SOCKET_NAME)
    subprocess.run(prefix + ["new-session", "-d", "-s", name, "-x", "91", "-y", "33", "-c", str(sub)], check=True)
    try:
        client = _client({"ses_1": _Info(name), "ses_gone": _Info("cloude_pf_missing")})
        body = client.get("/api/v1/sessions/ses_1/pane-facts").json()
        assert body["cwd"] and body["cwd"].endswith("/src/deep")
        assert body["git_branch"] == "main"
        assert body["command"]
        assert body["cols"] == 91
        gone = client.get("/api/v1/sessions/ses_gone/pane-facts").json()
        assert all(value is None for value in gone.values())
        assert client.get("/api/v1/sessions/nope/pane-facts").status_code == 404
    finally:
        subprocess.run(prefix + ["kill-session", "-t", f"={name}"], check=False)
