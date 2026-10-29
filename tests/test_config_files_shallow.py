from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cfs_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cfs_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

from src.core import config_files as cf  # noqa: E402
from src.core import config_files_tree_request as ctr  # noqa: E402
from src.api import config_files_routes as routes  # noqa: E402


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "fake-claude-home"
    home.mkdir()
    monkeypatch.setattr(cf, "CLAUDE_HOME", home)
    return home


@pytest.fixture()
def workdir(tmp_path):
    wd = tmp_path / "proj"
    (wd / "src" / "core").mkdir(parents=True)
    (wd / "src" / "app.py").write_text("x\n")
    (wd / "src" / "core" / "deep.py").write_text("y\n")
    (wd / "empty").mkdir()
    (wd / "README.md").write_text("hi\n")
    return wd


def _names(nodes):
    return [n["name"] for n in nodes]


def _by_name(nodes, name):
    for n in nodes:
        if n["name"] == name:
            return n
    raise AssertionError(f"{name!r} not in {_names(nodes)}")



def test_omitting_depth_returns_the_same_full_tree_as_before(workdir):
    full = cf.list_tree("workdir", str(workdir))
    src = _by_name(full, "src")
    assert _names(src["children"]) == ["core", "app.py"]
    assert _names(_by_name(src["children"], "core")["children"]) == ["deep.py"]


def test_depth_one_returns_one_level_and_says_the_rest_is_unloaded(workdir):
    nodes = cf.list_subtree("workdir", "", str(workdir), levels=1)
    assert _names(nodes) == ["empty", "src", "README.md"]
    src = _by_name(nodes, "src")
    assert src["children"] == []
    assert src["children_loaded"] is False


def test_an_empty_directory_is_not_confused_with_an_unloaded_one(workdir):
    nodes = cf.list_subtree("workdir", "", str(workdir), levels=2)
    empty = _by_name(nodes, "empty")
    core = _by_name(_by_name(nodes, "src")["children"], "core")
    assert empty["children"] == [] and core["children"] == []
    assert empty["children_loaded"] is True, "a read, empty directory"
    assert core["children_loaded"] is False, "stopped at the depth cap"


def test_a_file_reports_its_children_as_loaded(workdir):
    nodes = cf.list_subtree("workdir", "", str(workdir), levels=1)
    assert _by_name(nodes, "README.md")["children_loaded"] is True


def test_expanding_a_directory_returns_root_relative_paths(workdir):
    nodes = cf.list_subtree("workdir", "src", str(workdir), levels=1)
    assert _names(nodes) == ["core", "app.py"]
    assert _by_name(nodes, "app.py")["rel_path"] == "src/app.py"
    assert _by_name(nodes, "core")["rel_path"] == "src/core"


def test_expanding_twice_agrees_with_the_full_walk(workdir):
    full_src = _by_name(cf.list_tree("workdir", str(workdir)), "src")["children"]
    shallow_src = cf.list_subtree("workdir", "src", str(workdir), levels=2)
    assert _names(full_src) == _names(shallow_src)
    for a, b in zip(full_src, shallow_src):
        assert a["rel_path"] == b["rel_path"]
        assert a["is_dir"] == b["is_dir"]
        assert a["is_sensitive"] == b["is_sensitive"]
        assert a["read_only"] == b["read_only"]


def test_expanding_a_symlinked_directory_keeps_the_navigated_spelling(tmp_path):
    wd = tmp_path / "proj"
    real = wd / "real"
    real.mkdir(parents=True)
    (real / "ok.txt").write_text("yes\n")
    (wd / "self").symlink_to(real, target_is_directory=True)

    shallow = cf.list_subtree("workdir", "self", str(wd), levels=1)
    assert [n["rel_path"] for n in shallow] == ["self/ok.txt"]
    full_self = _by_name(cf.list_tree("workdir", str(wd)), "self")
    assert [n["rel_path"] for n in full_self["children"]] == ["self/ok.txt"]
    assert cf.read_file("workdir", "self/ok.txt", str(wd))["content"] == "yes\n"


def test_an_empty_root_still_lists_as_empty_not_as_an_error(fake_home):
    assert cf.list_subtree("user", "", None, levels=1) == []


def test_expanding_something_that_is_not_a_directory_is_a_client_error(workdir):
    with pytest.raises(cf.ConfigFileError):
        cf.list_subtree("workdir", "README.md", str(workdir), levels=1)



def test_no_depth_means_the_full_tree():
    plan = ctr.plan_tree_request(None, None)
    assert plan.rel_path == "" and plan.shallow is False
    assert plan.levels == ctr.FULL_TREE_LEVELS


@pytest.mark.parametrize("bad", [0, -1, ctr.FULL_TREE_LEVELS + 1, 99])
def test_an_out_of_range_depth_is_refused(bad):
    with pytest.raises(ValueError):
        ctr.plan_tree_request(None, bad)


@pytest.mark.parametrize("good", [1, 2, ctr.FULL_TREE_LEVELS])
def test_an_in_range_depth_is_accepted(good):
    assert ctr.plan_tree_request("hooks", good).levels == good



@pytest.mark.parametrize("attack", [
    "..",
    "../..",
    "src/..",
    "src/../..",
    "src/core/../../..",
    "/etc",
    "/",
    "src/./core",
])
def test_expansion_refuses_traversal_at_every_level(workdir, attack):
    with pytest.raises(cf.ConfigFileError):
        cf.list_subtree("workdir", attack, str(workdir), levels=1)


def test_expansion_refuses_a_symlink_bridge_out_of_the_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope\n")
    wd = tmp_path / "proj"
    wd.mkdir()
    (wd / "bridge").symlink_to(outside, target_is_directory=True)

    assert "bridge" in _names(cf.list_subtree("workdir", "", str(wd), levels=1))
    with pytest.raises(cf.ConfigFileError):
        cf.list_subtree("workdir", "bridge", str(wd), levels=1)


def test_expansion_refuses_a_sibling_whose_name_is_a_prefix_of_the_root(tmp_path):
    wd = tmp_path / "proj"
    wd.mkdir()
    evil = tmp_path / "projevil"
    evil.mkdir()
    (evil / "loot.txt").write_text("nope\n")
    (wd / "link").symlink_to(evil, target_is_directory=True)

    with pytest.raises(cf.ConfigFileError):
        cf.list_subtree("workdir", "link", str(wd), levels=1)
    inside = wd / "real"
    inside.mkdir()
    (inside / "ok.txt").write_text("yes\n")
    (wd / "self").symlink_to(inside, target_is_directory=True)
    assert _names(cf.list_subtree("workdir", "self", str(wd), levels=1)) == ["ok.txt"]


def test_expansion_opens_a_formerly_hidden_component(tmp_path):
    wd = tmp_path / "proj"
    (wd / "node_modules" / "pkg").mkdir(parents=True)
    assert _names(cf.list_subtree("workdir", "node_modules", str(wd), levels=1)) == ["pkg"]


def test_expansion_cannot_reach_a_non_allowlisted_top_level_entry(fake_home):
    (fake_home / "hooks").mkdir()
    (fake_home / "hooks" / "guard.py").write_text("# noop\n")
    (fake_home / "sneaky").mkdir()
    (fake_home / "sneaky" / "loot.txt").write_text("nope\n")

    with pytest.raises(cf.ConfigFileError):
        cf.list_subtree("user", "sneaky", None, levels=1)
    assert _names(cf.list_subtree("user", "hooks", None, levels=1)) == ["guard.py"]


def test_an_expansion_does_not_reapply_the_top_level_allowlist_to_its_children(fake_home):
    (fake_home / "hooks" / "sneaky").mkdir(parents=True)
    (fake_home / "hooks" / "sneaky" / "inner.py").write_text("# noop\n")
    nodes = cf.list_subtree("user", "hooks", None, levels=1)
    assert "sneaky" in _names(nodes)



def _run(coro):
    return asyncio.run(coro)


def test_route_returns_400_for_a_bad_depth(fake_home):
    with pytest.raises(HTTPException) as exc:
        _run(routes.get_config_file_tree(root="user", project_path=None, path=None, depth=0))
    assert exc.value.status_code == 400


def test_route_returns_400_for_a_traversal_path(workdir):
    with pytest.raises(HTTPException) as exc:
        _run(routes.get_config_file_tree(
            root="workdir", project_path=str(workdir), path="../..", depth=1))
    assert exc.value.status_code == 400


def test_route_returns_400_for_an_unknown_root():
    with pytest.raises(HTTPException) as exc:
        _run(routes.get_config_file_tree(
            root="nope", project_path=None, path=None, depth=None))
    assert exc.value.status_code == 400


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_route_returns_503_for_an_unreadable_directory_on_the_shallow_path(tmp_path):
    wd = tmp_path / "proj"
    locked = wd / "locked"
    locked.mkdir(parents=True)
    (locked / "inside.txt").write_text("x\n")
    os.chmod(locked, 0o000)
    try:
        with pytest.raises(HTTPException) as exc:
            _run(routes.get_config_file_tree(
                root="workdir", project_path=str(wd), path="locked", depth=1))
        assert exc.value.status_code == 503
    finally:
        os.chmod(locked, 0o755)


def test_route_returns_the_full_tree_when_no_new_parameters_are_sent(workdir):
    resp = _run(routes.get_config_file_tree(
        root="workdir", project_path=str(workdir), path=None, depth=None))
    src = _by_name(resp.tree, "src")
    assert _names(_by_name(src["children"], "core")["children"]) == ["deep.py"]




@pytest.fixture()
def http(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.auth import require_auth

    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}

    wd = tmp_path / "proj"
    (wd / "src" / "core").mkdir(parents=True)
    (wd / "src" / "app.py").write_text("x\n")
    (wd / "src" / "core" / "deep.py").write_text("y\n")
    (wd / "empty").mkdir()

    client = TestClient(app)

    def get(**params):
        return client.get("/api/v1/config-files/tree", params=params)

    return get, str(wd)


def test_http_an_old_client_sending_neither_parameter_gets_the_full_tree(http):
    get, wd = http
    resp = get(root="workdir", project_path=wd)
    assert resp.status_code == 200
    src = _by_name(resp.json()["tree"], "src")
    core = _by_name(src["children"], "core")
    assert _names(core["children"]) == ["deep.py"]
    assert core["children_loaded"] is True


def test_http_depth_one_returns_one_level(http):
    get, wd = http
    resp = get(root="workdir", project_path=wd, depth=1)
    assert resp.status_code == 200
    src = _by_name(resp.json()["tree"], "src")
    assert src["children"] == [] and src["children_loaded"] is False


def test_http_expanding_a_directory_returns_root_relative_paths(http):
    get, wd = http
    resp = get(root="workdir", project_path=wd, path="src", depth=1)
    assert resp.status_code == 200
    assert sorted(n["rel_path"] for n in resp.json()["tree"]) == ["src/app.py", "src/core"]


def test_http_an_empty_directory_succeeds_rather_than_erroring(http):
    get, wd = http
    resp = get(root="workdir", project_path=wd, path="empty", depth=1)
    assert resp.status_code == 200
    assert resp.json()["tree"] == []


@pytest.mark.parametrize("params,want", [
    ({"depth": 0}, 400),
    ({"depth": 99}, 400),
    ({"path": "../..", "depth": 1}, 400),
    ({"path": "/etc", "depth": 1}, 400),
])
def test_http_the_400_half_of_the_contract_is_unchanged(http, params, want):
    get, wd = http
    assert get(root="workdir", project_path=wd, **params).status_code == want


def test_http_an_unknown_root_is_still_a_400(http):
    get, _ = http
    assert get(root="nope").status_code == 400


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_http_an_unreadable_directory_is_a_503_not_a_400(http):
    get, wd = http
    locked = Path(wd) / "locked"
    locked.mkdir()
    (locked / "inside.txt").write_text("x\n")
    os.chmod(locked, 0o000)
    try:
        assert get(root="workdir", project_path=wd, path="locked", depth=1).status_code == 503
    finally:
        os.chmod(locked, 0o755)



def test_the_tree_walk_runs_off_the_event_loop(fake_home, monkeypatch):
    entered = threading.Event()
    released = threading.Event()

    def parked_walk(root_id, rel_path, project_path, levels):
        entered.set()
        if not released.wait(timeout=10.0):
            raise AssertionError(
                "the event loop never got to run while the walk was in progress: "
                "the walk is ON the loop"
            )
        return []

    monkeypatch.setattr(cf, "list_subtree", parked_walk)

    async def scenario():
        task = asyncio.create_task(routes.get_config_file_tree(
            root="user", project_path=None, path=None, depth=None))

        ticks = 0
        for _ in range(200):
            await asyncio.sleep(0.005)
            ticks += 1
            if entered.is_set():
                released.set()
                break
        resp = await task
        return ticks, resp

    ticks, resp = asyncio.run(scenario())
    assert entered.is_set(), "the walk never started"
    assert ticks > 0, "the loop was starved for the whole walk"
    assert resp.tree == []


def test_the_loop_test_can_detect_a_walk_that_is_on_the_loop():
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.001)
            ticks += 1

    async def scenario():
        nonlocal ticks
        hb = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.02)
        assert ticks > 0, "the heartbeat never started, so it proves nothing"
        before = ticks
        time.sleep(0.30)
        during = ticks - before
        hb.cancel()
        return during

    assert asyncio.run(scenario()) == 0, (
        "a synchronous 300ms call inside a coroutine let the loop run, so this "
        "harness cannot detect loop blocking and the test above is worthless"
    )
