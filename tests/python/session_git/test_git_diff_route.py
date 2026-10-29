
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.session_git_routes import router
from src.core.session_git.diff import MAX_BYTES

SID = "ses_1"


def _git(repo: Path, *args: str) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True, env=env)


@pytest.fixture()
def rig(tmp_path: Path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside.txt"
    outside.write_text("TOP SECRET OUTSIDE\n")
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for name, body in (("a.txt", "one\n"), ("-dash.txt", "d\n"), ("bin.dat", b"\0\1\2old"), (".env", "K=old\n")):
        (repo / name).write_bytes(body if isinstance(body, bytes) else body.encode())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / "a.txt").write_text("one\ntwo\n")
    (repo / "-dash.txt").write_text("d\nchanged\n")
    (repo / "bin.dat").write_bytes(b"\0\1\2new")
    (repo / ".env").write_text("K=new\n")
    (repo / "new.txt").write_text("fresh\nlines\n")
    (repo / "-untracked.txt").write_text("u\n")
    (repo / "blob.txt").write_text("")
    _git(repo, "add", "-N", "blob.txt")
    (repo / "big.txt").write_text("x" * (MAX_BYTES * 2))
    (repo / "bin_new.dat").write_bytes(b"\0\0\0")
    (repo / "escape").symlink_to(outside)
    (repo / "inside_link").symlink_to("a.txt")

    class Manager:
        _registry = None

        async def get_session_info(self, session_id):
            return SimpleNamespace(tmux_session=None, session=SimpleNamespace(working_dir=str(repo)))

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = Manager()
    with TestClient(app) as http:
        yield SimpleNamespace(http=http, repo=repo, get=lambda path, **q: http.get(
            f"/api/v1/sessions/{SID}/git-diff", params={"path": path, **q}))


def test_diff_route(rig) -> None:
    ok = rig.get("a.txt")
    assert ok.status_code == 200 and "+two" in ok.json()["text"] and ok.json()["state"] == "ok"
    assert "+two" in rig.get("a.txt", staged="false").json()["text"]

    assert "+changed" in rig.get("-dash.txt").json()["text"]
    u = rig.get("-untracked.txt").json()
    assert u["untracked"] and "+u" in u["text"] and "/dev/null" in u["text"]
    new = rig.get("new.txt").json()
    assert new["untracked"] and "@@ -0,0 +1,2 @@" in new["text"] and "+fresh" in new["text"]

    for bad in ("../outside.txt", "sub/../a.txt", "/etc/passwd", "a\0b"):
        assert rig.get(bad).status_code == 400, bad
    assert rig.get("not_in_listing.txt").status_code == 404
    assert rig.get(".git/config").status_code == 404
    assert rig.get("--output=/tmp/x").status_code == 404

    esc = rig.get("escape")
    assert esc.status_code == 403 and "SECRET" not in esc.text
    assert "a.txt" in rig.get("inside_link").json()["text"]

    for name in ("bin.dat", "bin_new.dat"):
        b = rig.get(name).json()
        assert b["binary"] is True and b["text"] == ""

    big = rig.get("big.txt").json()
    assert big["truncated"] is True and len(big["text"].encode()) <= MAX_BYTES

    env = rig.get(".env").json()
    assert env["sensitive"] is True and env["text"] == "" and "new" not in str(env)

    assert rig.get("blob.txt").json()["state"] == "ok"

    (rig.repo / ".git" / "HEAD").write_text("garbage\n")
    broken = rig.get("a.txt")
    assert broken.json()["state"] == "unknown" and broken.json()["text"] == ""
