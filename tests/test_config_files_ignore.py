from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cfi_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cfi_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config_files_ignore as cfi  # noqa: E402
from src.api import config_files_routes as routes  # noqa: E402

HAS_GIT = shutil.which("git") is not None


def _by_name(nodes: list, name: str) -> dict:
    return next(n for n in nodes if n["name"] == name)


@pytest.fixture()
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.auth import require_auth

    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    tc = TestClient(app)

    def get(**params):
        return tc.get("/api/v1/config-files/tree", params=params)

    return get


def _project(base: Path) -> Path:
    wd = base / "proj"
    (wd / "out").mkdir(parents=True)
    (wd / "out" / "bundle.js").write_text("x\n")
    (wd / "src").mkdir()
    (wd / "src" / "app.py").write_text("x\n")
    (wd / "src" / "trace.log").write_text("x\n")
    (wd / ".gitignore").write_text("out/\n*.log\n")
    (wd / "README.md").write_text("x\n")
    return wd


@pytest.fixture()
def repo(tmp_path):
    if not HAS_GIT:
        pytest.skip("git is not installed")
    wd = _project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=wd, check=True)
    return wd


def test_ignored_entries_are_marked_in_a_repository(client, repo):
    resp = client(root="workdir", project_path=str(repo), ignored="true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ignore_status"] == "ok"
    tree = body["tree"]
    out = _by_name(tree, "out")
    assert out["is_ignored"] is True
    assert _by_name(out["children"], "bundle.js")["is_ignored"] is True
    src = _by_name(tree, "src")
    assert src["is_ignored"] is False
    assert _by_name(src["children"], "trace.log")["is_ignored"] is True
    assert _by_name(src["children"], "app.py")["is_ignored"] is False
    assert _by_name(tree, "README.md")["is_ignored"] is False
    assert _by_name(tree, ".gitignore")["is_ignored"] is False


def test_a_shallow_expansion_is_marked_with_root_relative_paths(client, repo):
    resp = client(root="workdir", project_path=str(repo), path="src", depth=1, ignored="true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ignore_status"] == "ok"
    marks = {n["rel_path"]: n["is_ignored"] for n in body["tree"]}
    assert marks == {"src/app.py": False, "src/trace.log": True}


def test_without_the_flag_the_response_is_the_old_shape(client, repo):
    resp = client(root="workdir", project_path=str(repo), depth=1)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ignore_status"] is None
    assert all("is_ignored" not in n for n in body["tree"])


def test_a_folder_that_is_not_a_repository_hides_nothing(client, tmp_path, monkeypatch):
    if not HAS_GIT:
        pytest.skip("git is not installed")
    wd = _project(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    resp = client(root="workdir", project_path=str(wd), ignored="true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ignore_status"] == "unavailable"
    assert all("is_ignored" not in n for n in body["tree"])
    assert {n["name"] for n in body["tree"]} == {".gitignore", "README.md", "out", "src"}


def test_no_git_on_the_machine_hides_nothing(client, repo, monkeypatch):
    def missing(*_a, **_k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(cfi.subprocess, "run", missing)
    resp = client(root="workdir", project_path=str(repo), ignored="true")
    assert resp.status_code == 200
    assert resp.json()["ignore_status"] == "unavailable"


def test_a_git_timeout_hides_nothing(client, repo, monkeypatch):
    def slow(*_a, **_k):
        raise subprocess.TimeoutExpired("git", cfi.TIMEOUT_S)
    monkeypatch.setattr(cfi.subprocess, "run", slow)
    resp = client(root="workdir", project_path=str(repo), ignored="true")
    assert resp.json()["ignore_status"] == "unavailable"


def test_more_paths_than_the_bound_hides_nothing(client, repo, monkeypatch):
    monkeypatch.setattr(cfi, "MAX_PATHS", 2)
    resp = client(root="workdir", project_path=str(repo), ignored="true")
    assert resp.json()["ignore_status"] == "unavailable"


@pytest.mark.parametrize("attack", ["..", "../..", "/etc", "src/../../"])
def test_the_flag_does_not_widen_what_can_be_listed(client, repo, attack):
    without = client(root="workdir", project_path=str(repo), path=attack, depth=1)
    with_flag = client(root="workdir", project_path=str(repo), path=attack, depth=1, ignored="true")
    assert without.status_code == 400
    assert with_flag.status_code == 400


def test_git_is_asked_only_about_the_walks_own_output(client, repo, monkeypatch):
    seen = {}
    real = cfi.subprocess.run

    def spy(cmd, **kwargs):
        seen["cwd"] = kwargs["cwd"]
        seen["paths"] = [p for p in kwargs["input"].decode().split("\0") if p]
        seen["cmd"] = cmd
        return real(cmd, **kwargs)

    monkeypatch.setattr(cfi.subprocess, "run", spy)
    resp = client(root="workdir", project_path=str(repo), ignored="true")
    assert resp.status_code == 200
    assert Path(seen["cwd"]) == repo.resolve()
    for p in seen["paths"]:
        assert p.startswith("./")
        p = p[2:]
        assert not p.startswith("/") and ".." not in p.split("/")
    assert sorted(p[2:] for p in seen["paths"]) == sorted([
        ".gitignore", "README.md", "out/", "out/bundle.js", "src/", "src/app.py", "src/trace.log",
    ])
    assert "core.fsmonitor=false" in seen["cmd"]


def test_a_symlinked_directory_does_not_switch_the_option_off(client, repo):
    (repo / "lib").symlink_to("src", target_is_directory=True)
    resp = client(root="workdir", project_path=str(repo), ignored="true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ignore_status"] == "ok"
    tree = body["tree"]
    assert _by_name(tree, "out")["is_ignored"] is True
    assert _by_name(_by_name(tree, "src")["children"], "trace.log")["is_ignored"] is True
    lib = _by_name(tree, "lib")
    assert lib["is_ignored"] is False
    assert lib["children"], "the walk no longer descends through a symlink; this test proves nothing"
    assert all(c["is_ignored"] is False for c in lib["children"])


def test_expanding_a_symlinked_directory_is_still_marked(client, repo):
    (repo / "lib").symlink_to("src", target_is_directory=True)
    resp = client(root="workdir", project_path=str(repo), path="lib", depth=1, ignored="true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ignore_status"] == "ok"
    marks = {n["rel_path"]: n["is_ignored"] for n in body["tree"]}
    assert marks == {"lib/app.py": False, "lib/trace.log": False}


@pytest.mark.parametrize("name", [":(exclude)z", ":!bang", ":^caret"])
def test_a_file_named_like_pathspec_magic_does_not_switch_the_option_off(client, repo, name):
    (repo / name).write_text("x\n")
    with (repo / ".gitignore").open("a") as fh:
        fh.write("/" + name + "\n")
    resp = client(root="workdir", project_path=str(repo), ignored="true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ignore_status"] == "ok"
    assert _by_name(body["tree"], name)["is_ignored"] is True
    assert _by_name(body["tree"], "out")["is_ignored"] is True
    assert _by_name(body["tree"], "README.md")["is_ignored"] is False
