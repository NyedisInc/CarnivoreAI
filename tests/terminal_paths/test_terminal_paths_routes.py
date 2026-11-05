
from __future__ import annotations

import plistlib
from typing import Optional

import pytest

from src.core.terminal_paths import open_app


class _Session:
    def __init__(self, working_dir: str) -> None:
        self.working_dir = working_dir


class _Info:

    def __init__(self, working_dir: str) -> None:
        self.tmux_session: Optional[str] = None
        self.session = _Session(working_dir)


class _Manager:
    def __init__(self, rows: dict) -> None:
        self._rows = rows

    async def get_session_info(self, session_id: Optional[str] = None):
        return self._rows.get(session_id)

    def tmux_socket_name(self) -> str:
        return "unused"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "README.md").write_text("hi\n")
    return tmp_path


@pytest.fixture
def client(repo, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = _Manager({"ses_1": _Info(str(repo))})
    ran: list[list[str]] = []

    async def fake_run(argv: list[str]) -> None:
        ran.append(argv)

    monkeypatch.setattr(open_app, "run_open", fake_run)
    monkeypatch.setattr(open_app, "default_browser", lambda *a: "com.example.browser")
    monkeypatch.setattr(open_app.sys, "platform", "darwin")
    c = TestClient(app)
    c.ran = ran  # type: ignore[attr-defined]
    return c


def test_resolve_answers_only_paths_that_exist(client, repo):
    texts = ["src/a.py:12:3", "README.md", str(repo / "src"), "missing.txt", "~/../../../nope-2753"]
    answer = client.post("/api/v1/sessions/ses_1/paths/resolve", json={"texts": texts})
    assert answer.status_code == 200
    rows = answer.json()["paths"]
    assert [r["text"] for r in rows] == texts
    assert rows[0] == {"text": texts[0], "path": str(repo / "src" / "a.py"), "kind": "file", "line": 12}
    assert rows[1]["path"] == str(repo / "README.md") and rows[1]["line"] is None
    assert rows[2]["kind"] == "dir"
    assert rows[3]["path"] is None and rows[4]["path"] is None


def test_resolve_refuses_an_unknown_session(client):
    assert client.post("/api/v1/sessions/ses_x/paths/resolve", json={"texts": ["a"]}).status_code == 404


def test_open_runs_finder_and_the_default_browser_with_an_argv_list(client, repo):
    ok = client.post("/api/v1/sessions/ses_1/paths/open", json={"text": "src/a.py:4", "app": "finder"})
    assert ok.status_code == 200 and ok.json()["path"] == str(repo / "src" / "a.py")
    ok = client.post("/api/v1/sessions/ses_1/paths/open", json={"text": "README.md", "app": "browser"})
    assert ok.status_code == 200
    assert client.ran == [["open", "-R", str(repo / "src" / "a.py")],
                          ["open", "-b", "com.example.browser", str(repo / "README.md")]]


def test_open_refuses_a_missing_path_and_a_folder_in_the_browser(client):
    assert client.post("/api/v1/sessions/ses_1/paths/open", json={"text": "nope.md", "app": "finder"}).status_code == 404
    assert client.post("/api/v1/sessions/ses_1/paths/open", json={"text": "src", "app": "browser"}).status_code == 400
    assert client.ran == []


def test_both_routes_refuse_a_caller_with_no_login(client):
    client.app.dependency_overrides.clear()
    assert client.post("/api/v1/sessions/ses_1/paths/resolve", json={"texts": ["a"]}).status_code == 401
    assert client.post("/api/v1/sessions/ses_1/paths/open", json={"text": "a", "app": "finder"}).status_code == 401
    assert client.ran == []


def test_default_browser_reads_the_https_handler(tmp_path):
    plist = tmp_path / "ls.plist"
    plist.write_bytes(plistlib.dumps({"LSHandlers": [{"LSHandlerURLScheme": "mailto", "LSHandlerRoleAll": "m"},
                                                     {"LSHandlerURLScheme": "https", "LSHandlerRoleAll": "com.brave.browser"}]}))
    assert open_app.default_browser(plist) == "com.brave.browser"
    assert open_app.default_browser(tmp_path / "none.plist") == open_app.FALLBACK_BROWSER
