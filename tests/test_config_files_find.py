from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cff_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cff_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config_files as cf  # noqa: E402
from src.core import config_files_find as cff  # noqa: E402
from src.api import config_files_routes as routes  # noqa: E402


def _names(nodes: list) -> list:
    return [n["name"] for n in nodes]


def _by_name(nodes: list, name: str) -> dict:
    return next(n for n in nodes if n["name"] == name)


def _all_paths(nodes: list) -> list:
    out = []
    for n in nodes:
        out.append(n["rel_path"])
        out.extend(_all_paths(n["children"]))
    return out


@pytest.fixture()
def find():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.auth import require_auth

    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    tc = TestClient(app)
    return lambda **params: tc.get("/api/v1/config-files/find", params=params)


@pytest.fixture()
def workdir(tmp_path):
    wd = tmp_path / "proj"
    (wd / "src" / "core" / "deep").mkdir(parents=True)
    (wd / "src" / "core" / "deep" / "Readme_Deep.md").write_text("x\n")
    (wd / "src" / "app.py").write_text("x\n")
    (wd / "docs").mkdir()
    (wd / "docs" / "readme-docs.md").write_text("x\n")
    (wd / "README.md").write_text("x\n")
    (wd / "node_modules" / "pkg").mkdir(parents=True)
    (wd / "node_modules" / "pkg" / "readme.md").write_text("x\n")
    (wd / ".git").mkdir()
    (wd / ".git" / "README").write_text("x\n")
    return wd


def test_finds_names_at_any_depth_ignoring_case(find, workdir):
    resp = find(root="workdir", project_path=str(workdir), q="README")
    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is False
    assert sorted(p for p in _all_paths(body["tree"]) if p.lower().endswith(".md")) == [
        "README.md", "docs/readme-docs.md", "node_modules/pkg/readme.md", "src/core/deep/Readme_Deep.md",
    ]
    assert _names(body["tree"]) == [".git", "docs", "node_modules", "src", "README.md"]
    src = _by_name(body["tree"], "src")
    assert src["children_loaded"] is False
    assert _names(src["children"]) == ["core"]
    assert _by_name(src["children"], "core")["children"][0]["name"] == "deep"


def test_former_hide_list_is_searched(find, workdir):
    resp = find(root="workdir", project_path=str(workdir), q="readme")
    paths = _all_paths(resp.json()["tree"])
    assert "node_modules/pkg/readme.md" in paths
    assert ".git/README" in paths


def test_the_user_root_keeps_its_top_level_allowlist(find, tmp_path, monkeypatch):
    home = tmp_path / "claude-home"
    (home / "hooks").mkdir(parents=True)
    (home / "hooks" / "guard.py").write_text("x\n")
    (home / "not-allowed").mkdir()
    (home / "not-allowed" / "guard.py").write_text("x\n")
    monkeypatch.setattr(cf, "CLAUDE_HOME", home)
    resp = find(root="user", q="guard")
    assert resp.status_code == 200
    assert _all_paths(resp.json()["tree"]) == ["hooks", "hooks/guard.py"]


@pytest.mark.parametrize("attack", ["..", "../..", "/etc", "src/../../"])
def test_a_traversal_path_is_refused(find, workdir, attack):
    resp = find(root="workdir", project_path=str(workdir), q="a", path=attack)
    assert resp.status_code == 400


def test_a_symlink_out_of_the_root_is_never_followed(find, workdir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret-readme.txt").write_text("x\n")
    (workdir / "bridge").symlink_to(outside, target_is_directory=True)
    resp = find(root="workdir", project_path=str(workdir), q="secret")
    assert resp.status_code == 200
    assert resp.json()["tree"] == []
    resp = find(root="workdir", project_path=str(workdir), q="bridge")
    tree = resp.json()["tree"]
    assert _names(tree) == ["bridge"] and tree[0]["children"] == []


def test_a_search_can_be_scoped_to_one_directory(find, workdir):
    resp = find(root="workdir", project_path=str(workdir), q="readme", path="docs")
    assert resp.status_code == 200
    assert _all_paths(resp.json()["tree"]) == ["docs/readme-docs.md"]


@pytest.mark.parametrize("q", ["", "   ", "x" * 201])
def test_an_empty_or_overlong_query_is_refused(find, workdir, q):
    assert find(root="workdir", project_path=str(workdir), q=q).status_code in (400, 422)


def test_an_unknown_root_is_refused(find):
    assert find(root="nope", q="a").status_code == 400


def test_the_match_limit_truncates(workdir):
    tree, truncated = cff.find("workdir", "", str(workdir), "readme", limit=1)
    assert truncated is True
    assert len([p for p in _all_paths(tree) if "eadme" in p.lower()]) == 1


def test_the_time_budget_truncates(workdir, monkeypatch):
    monkeypatch.setattr(cff, "FIND_BUDGET_S", -1.0)
    tree, truncated = cff.find("workdir", "", str(workdir), "readme")
    assert truncated is True and tree == []


def test_marks_ignored_when_asked(find, workdir):
    import shutil
    import subprocess
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    (workdir / ".gitignore").write_text("docs/\n")
    body = find(root="workdir", project_path=str(workdir), q="readme", ignored="true").json()
    assert body["ignore_status"] == "ok"
    docs = _by_name(body["tree"], "docs")
    assert docs["is_ignored"] is True
    assert _by_name(body["tree"], "README.md")["is_ignored"] is False
