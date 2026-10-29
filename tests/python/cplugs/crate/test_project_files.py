
from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

import pytest

from src.core.inventory import registry, state_files
from src.cplugs.crate import constants as K
from src.cplugs.crate import project_files as PF
from src.cplugs.crate import project_git as PG
from src.cplugs.crate import service
from src.cplugs.crate.errors import CrateApiError
from src.cplugs.crate.forbidden import project_root_problem
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request, session_request

TOKEN = "ghp_" + "x" * 36
GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")


def _git(root: Path, *args: str) -> str:
    return subprocess.run([*GIT, *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _tree(root: Path, files: Dict[str, bytes]) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    assert shutil.which("git"), "git is needed for the project_git cases"
    w = make_world(tmp_path)
    root, outside = Path(w.root1), tmp_path / "outside"
    _tree(outside, {"secret.txt": b"outside the project\n"})
    _tree(root, {
        "src/app.py": b"print('one')\n", "README.md": b"# app\n", ".env": f"TOKEN={TOKEN}\n".encode(),
        "config.toml": b"[a]\nb = 1\n", "auth.json": b"{}\n", "empty.txt": b"", "data/blob.bin": bytes(range(256)) * 100,
        "node_modules/pkg/index.js": b"x" * 5000, "dist/out.js": b"y" * 300, "sub/__pycache__/m.pyc": b"z" * 70,
        "a/node_modules.nosync/p.js": b"q" * 40, "src/.DS_Store": b"ds",
    })
    os.symlink("src/app.py", root / "latest")
    os.symlink(outside, root / "ext")
    os.mkfifo(root / "pipe")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "src/app.py", "README.md", "config.toml")
    _git(root, "commit", "-q", "-m", "first")
    (root / "src/app.py").write_text("print('two')\n")
    (root / "untracked.txt").write_text("new\n")
    w.root, w.outside = root, outside
    return w


def _export(w: SimpleNamespace, request):  # noqa: ANN001, ANN201
    env = env_for(w)
    plan = build_plan(env, request)
    assert plan.ok, plan.blockers
    return plan, run_export(env, plan, JobHandle("p"))


def test_the_plan_walks_the_folder_and_names_what_it_skipped(world: SimpleNamespace) -> None:
    plan = build_plan(env_for(world), project_request(world, include_project_files=True))
    assert plan.ok, plan.blockers
    view = plan.project
    carried = {f.rel for f in plan.files if f.home == "project"}
    assert carried == {"src/app.py", "README.md", ".env", "config.toml", "auth.json", "empty.txt", "data/blob.bin",
                       "untracked.txt", "latest", "ext", ".cc.theme"}
    skipped = {d["path"]: d["bytes"] for d in view["skipped"]}
    git_bytes = skipped.pop(".git")
    assert git_bytes > 0 and skipped == {"node_modules": 5000, "dist": 300, "sub/__pycache__": 70, "a/node_modules.nosync": 40}
    assert view["skipped_bytes"] == git_bytes + 5000 + 300 + 70 + 40 + 2 and view["links"] == 2 and view["specials"] == ["pipe"]
    assert view["files"] == len(carried) and view["large"] is False and view["warn_bytes"] == K.PROJECT_WARN_BYTES
    assert {"what": "pipe"}.items() <= next(e for e in plan.excluded if e.get("what") == "pipe").items()
    assert not [f for f in plan.files if f.home == "project" and ".git" in f.rel.split("/")]


def test_off_by_default_changes_nothing(world: SimpleNamespace) -> None:
    plan, result = _export(world, project_request(world))
    assert plan.project is None and not [f for f in plan.files if f.home == "project"]
    with cf.open_crate(result.path) as reader:
        assert reader.format_version == (1, 0) and "project_git" not in reader.manifest.extra
        assert not [h for h in reader.manifest.homes if h.kind == "project"]
        assert not reader.has(cf.constants.M_PROJECT_PATCH)


def test_the_export_round_trips_with_git_state_secrets_and_links(world: SimpleNamespace, tmp_path: Path) -> None:
    plan, result = _export(world, project_request(world, include_project_files=True))
    report = cf.verify(result.path, "drill", expected_sha256=result.sha256, scratch=tmp_path)
    assert report.ok, report.problems
    with cf.open_crate(result.path) as reader:
        manifest, records = reader.manifest, {(r.home, r.rel): r for r in reader.files()}
        assert reader.format_version == (1, 1)
        assert {"kind": "project", "index": 0, "path": str(world.root.resolve())} in [h.as_json() for h in manifest.homes]
        project = {rel: r for (home, rel), r in records.items() if home == "project"}
        assert project["latest"].role == "project_link" and project["latest"].extra["link_target"] == "src/app.py"
        assert project["latest"].length == len("src/app.py")
        assert project["ext"].extra["link_target"] == str(world.outside)
        assert not [rel for rel in project if rel.startswith("ext/") or rel == "secret.txt"]
        assert {r.role for rel, r in project.items() if rel not in ("latest", "ext")} == {"project_file"}
        assert project["config.toml"].length and project["auth.json"].length
        git = manifest.extra["project_git"]
        assert git["branch"] == "main" and git["detached"] is False and git["dirty"] is True
        assert git["head"] == _git(world.root, "rev-parse", "HEAD").strip()
        assert git["untracked"] == [".cc.theme", ".env", "auth.json", "data/blob.bin", "empty.txt", "ext", "latest",
                                    "untracked.txt"] and git["untracked_count"] == 8 and git["untracked_truncated"] is False
        assert git["patch_member"] == "project/uncommitted.patch"
        patch = reader.read_member("project/uncommitted.patch").decode()
        assert "-print('one')" in patch and "+print('two')" in patch
        assert "project/uncommitted.patch" in {m.name for m in manifest.members}
        by_file = json.loads(reader.read_member("secrets.json"))["by_file"]
        assert by_file["project/0/.env"] == {"github_token": 1} and manifest.secrets["findings"] >= 1
        out = cf.extract_all(reader, tmp_path / "all")
    assert (tmp_path / "all/project/src/app.py").read_text() == "print('two')\n"
    assert (tmp_path / "all/project/.env").read_text() == f"TOKEN={TOKEN}\n"
    assert not (tmp_path / "all/project/.git").exists() and "project/node_modules/pkg/index.js" not in out.files


def test_the_embedded_extract_py_files_the_project(world: SimpleNamespace, tmp_path: Path) -> None:
    _plan, result = _export(world, project_request(world, include_project_files=True))
    tool, dest = tmp_path / "tool", tmp_path / "dest"
    tool.mkdir()
    with cf.open_crate(result.path) as reader:
        (tool / "extract.py").write_bytes(reader.read_member(cf.constants.M_EXTRACT))
    run = subprocess.run(["python3", "-I", "extract.py", str(result.path), str(dest)], cwd=tool, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert (dest / "project/src/app.py").read_text() == "print('two')\n" and (dest / "project/data/blob.bin").stat().st_size == 25600


def test_a_session_export_carries_the_working_folder(world: SimpleNamespace) -> None:
    plan = build_plan(env_for(world), session_request(include_project_files=True))
    assert plan.ok, plan.blockers
    assert plan.project["root"] == str(world.root.resolve()) and plan.project["files"] == 11


def test_a_folder_that_is_not_a_repository_records_null(world: SimpleNamespace) -> None:
    shutil.rmtree(world.root / ".git")
    _plan, result = _export(world, project_request(world, include_project_files=True))
    with cf.open_crate(result.path) as reader:
        assert reader.manifest.extra["project_git"] is None and not reader.has(cf.constants.M_PROJECT_PATCH)
        assert reader.format_version == (1, 1)


def test_the_patch_is_scanned_for_credentials(world: SimpleNamespace) -> None:
    (world.root / "README.md").write_text(f"# app\nkey {TOKEN}\n")
    _plan, result = _export(world, project_request(world, include_project_files=True))
    with cf.open_crate(result.path) as reader:
        by_file = json.loads(reader.read_member("secrets.json"))["by_file"]
    assert by_file[cf.constants.M_PROJECT_PATCH] == {"github_token": 1}


def test_a_share_is_refused_not_ignored(world: SimpleNamespace) -> None:
    env = env_for(world)
    with pytest.raises(CrateApiError) as caught:
        service.request_of(env, {"scope": "project", "target": world.root1, "variant": "share", "include_project_files": True})
    assert caught.value.code == "project_files_share"
    with pytest.raises(ValueError):
        build_plan(env, project_request(world, "share", include_project_files=True))
    with pytest.raises(CrateApiError) as bad:
        service.request_of(env, {"scope": "project", "target": world.root1, "include_project_files": "yes"})
    assert bad.value.code == "bad_project_files"
    assert service.request_of(env, {"scope": "project", "target": world.root1}).include_project_files is False


def test_a_missing_folder_fails_the_plan(world: SimpleNamespace) -> None:
    shutil.rmtree(world.root)
    plan = build_plan(env_for(world), project_request(world, include_project_files=True))
    assert not plan.ok and [b["code"] for b in plan.blockers if b["code"] == K.B_PROJECT_ROOT]


def test_a_folder_inside_or_holding_a_live_home_is_refused(world: SimpleNamespace) -> None:
    home = Path(world.home)
    assert "inside a live harness home" in project_root_problem(str(home / "projects"), world.locations)
    assert "holds a live harness home" in project_root_problem(str(home.parent), world.locations)
    assert project_root_problem(world.root1, world.locations) is None


def test_a_large_folder_raises_the_flag(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(K, "PROJECT_WARN_BYTES", 1000)
    plan = build_plan(env_for(world), project_request(world, include_project_files=True))
    assert plan.project["large"] is True and plan.project["warn_bytes"] == 1000


@pytest.mark.parametrize("name,skipped", [("node_modules", True), ("venv", True), (".venv", True), ("x.nosync", True),
                                          ("__pycache__", True), (".pytest_cache", True), (".ruff_cache", True),
                                          (".mypy_cache", True), (".next", True), (".turbo", True), (".svelte-kit", True), (".vite", True),
                                          (".gradle", True),
                                          ("target", True), ("dist", True), ("build", True), (".DS_Store", True),
                                          (".git", True), (".gitignore", False), ("src", False), ("builds", False),
                                          ("nosync", False)])
def test_the_skip_list_is_a_fixed_name_match(name: str, skipped: bool) -> None:
    assert PF.is_skipped(name) is skipped
    assert PF.skipped_component(f"a/{name}/b") is skipped


def test_a_gitignore_is_not_read(world: SimpleNamespace) -> None:
    (world.root / ".gitignore").write_text("data/\n*.md\n")
    plan = build_plan(env_for(world), project_request(world, include_project_files=True))
    rels = {f.rel for f in plan.files if f.home == "project"}
    assert {".gitignore", "data/blob.bin", "README.md"} <= rels


def test_the_two_unaccounted_stores_are_classified(tmp_path: Path) -> None:
    kinds = {s.store: s.kind for s in registry.book().stores}
    assert kinds["ai_summaries.db"] == "dormant" and kinds["cplugs/mcpondemand/mcpondemand.db"] == "dormant"
    (tmp_path / "cplugs/mcpondemand").mkdir(parents=True)
    (tmp_path / "ai_summaries.db").write_bytes(b"")
    (tmp_path / "cplugs/mcpondemand/mcpondemand.db").write_bytes(b"")
    assert state_files.unaccounted(tmp_path) == []




def _walk(root: Path, deny=frozenset()) -> PF.ProjectWalk:  # noqa: ANN001
    return PF.walk_project(str(root), set(deny))


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything")
def test_unreadable_paths_are_skipped_and_listed_not_blocking(tmp_path: Path) -> None:
    _tree(tmp_path, {"ok.txt": b"x", "locked/f.txt": b"y", "private.log": b"z"})
    (tmp_path / "private.log").chmod(0)
    (tmp_path / "locked").chmod(0)
    try:
        walk = _walk(tmp_path)
    finally:
        (tmp_path / "locked").chmod(0o755)
    assert walk.blockers == [] and [f.rel for f in walk.files] == ["ok.txt"]
    assert walk.specials == ["locked", "private.log"]


def test_an_icloud_evicted_folder_is_dataless_not_forbidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _tree(tmp_path, {"ok.txt": b"x", "gone/f.txt": b"y"})
    real = os.scandir

    def scandir(path):  # noqa: ANN001, ANN202
        if str(path).endswith("gone"):
            raise OSError(errno.EDEADLK, "Resource deadlock avoided")
        return real(path)

    monkeypatch.setattr(PF.os, "scandir", scandir)
    assert [c for c, _ in _walk(tmp_path).blockers] == [K.B_DATALESS]


def test_a_dataless_file_and_a_credential_hard_link_still_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _tree(tmp_path, {"cloud.txt": b"x", "linked.txt": b"secret"})
    st = (tmp_path / "linked.txt").stat()
    monkeypatch.setattr(PF.dataless, "is_dataless_file", lambda path: path.name == "cloud.txt")
    walk = _walk(tmp_path, {(st.st_dev, st.st_ino)})
    assert sorted(c for c, _ in walk.blockers) == [K.B_DATALESS, K.B_FORBIDDEN] and walk.files == []


def test_the_preview_counts_skipped_folders_it_does_not_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _tree(tmp_path, {f"p{i}/node_modules/x": b"1" * (i + 1) for i in range(4)})
    monkeypatch.setattr(K, "PROJECT_SKIPPED_LISTED", 3)
    view = _walk(tmp_path).view()
    assert len(view["skipped"]) == 3 and view["skipped_folders"] == 4 and view["skipped_more"] == 1


def test_a_skipped_name_that_is_not_utf8_is_listed_as_a_special(tmp_path: Path) -> None:
    try:
        os.mkdir(os.fsencode(str(tmp_path)) + b"/\xff.nosync")
    except OSError:
        pytest.skip("this filesystem refuses non-UTF-8 names")
    walk = _walk(tmp_path)
    assert walk.skipped == [] and len(walk.specials) == 1
    json.dumps(walk.excluded(), ensure_ascii=False).encode("utf-8")


def test_a_folder_inside_a_repository_is_recorded_and_scoped(world: SimpleNamespace) -> None:
    top = world.root
    _tree(top, {"web/w.txt": b"1\n", "other.txt": b"1\n"})
    _git(top, "add", "web/w.txt", "other.txt")
    _git(top, "commit", "-q", "-m", "more")
    (top / "web/w.txt").write_text("2\n")
    (top / "other.txt").write_text("outside\n")
    (top / "web/new.txt").write_text("n\n")
    snap = PG.snapshot(str(top / "web"))
    assert snap is not None and snap.block["untracked"] == ["new.txt"] and snap.block["dirty"] is True
    assert snap.patch is not None and b"w.txt" in snap.patch and b"other.txt" not in snap.patch
    assert b"a/w.txt" in snap.patch


def test_a_stub_git_folder_does_not_borrow_the_parent_repository(world: SimpleNamespace) -> None:
    stub = world.root / "stub"
    (stub / ".git").mkdir(parents=True)
    assert PG.snapshot(str(stub)) is None


def test_the_patch_ignores_the_users_git_config(world: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("[color]\n\tui = always\n[diff]\n\tnoprefix = true\n")
    monkeypatch.setenv("HOME", str(home))
    snap = PG.snapshot(str(world.root))
    assert snap is not None and snap.patch is not None
    assert b"\x1b" not in snap.patch and b"diff --git a/src/app.py b/src/app.py" in snap.patch


def test_a_configured_clean_filter_never_runs(world: SimpleNamespace, tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    root = world.root
    (root / ".gitattributes").write_text("*.py filter=x\n")
    _git(root, "config", "filter.x.clean", f"touch {marker}; cat")
    (root / "src/app.py").write_text("print('t00')\n")
    assert PG.snapshot(str(root)) is not None
    assert not marker.exists()


def test_a_non_utf8_untracked_name_survives_json() -> None:
    _dirty, names = PG._untracked(b"?? \xff.txt\0")
    json.dumps(names, ensure_ascii=False).encode("utf-8")
    assert len(names) == 1


def test_the_patch_key_cannot_collide_with_a_project_file(world: SimpleNamespace) -> None:
    (world.root / "uncommitted.patch").write_text(f"{TOKEN}\n")
    (world.root / "README.md").write_text(f"# app\n{TOKEN}\n")
    _plan, result = _export(world, project_request(world, include_project_files=True))
    with cf.open_crate(result.path) as reader:
        by_file = json.loads(reader.read_member("secrets.json"))["by_file"]
    assert by_file["project/0/uncommitted.patch"] == {"github_token": 1}
    assert by_file[cf.constants.M_PROJECT_PATCH] == {"github_token": 1}
