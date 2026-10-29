
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.federation_pack_span_routes import BoardBody, board_verb
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.reviewboard import root as board_root
from src.cplugs.reviewboard.errors import NoRoot
from tests.python.cplugs.reviewboard.boards import SIDECAR, make_board, sidecar
from tests.python.cplugs.reviewboard.harness import BASE, Env, make_env


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return make_env(tmp_path)


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


def second_board(env: Env, slug: str = "20261014-side-panel", item: int = 530, round_at: str = "2026-10-14T09:00:00Z"):
    raw = copy.deepcopy(SIDECAR)
    raw["board"]["slug"], raw["board"]["title"], raw["task"]["item_id"] = slug, "side panel", item
    raw["rounds"][0]["sent_at"] = round_at
    raw["rounds"][0]["delivery"]["item_id"] = item
    return make_board(env.root, raw)



def refusal(value, state_dir=None) -> str:
    with pytest.raises(NoRoot) as caught:
        board_root.check_root(value, state_dir)
    return caught.value.reason


def test_a_good_folder_is_accepted(env: Env):
    assert board_root.check_root(str(env.root), env.host.state_dir) == env.root


def test_every_unusable_folder_is_refused_with_its_own_reason(env: Env, tmp_path: Path):
    state = env.host.state_dir
    assert refusal(None, state) == "unset" and refusal("  ", state) == "unset" and refusal(42, state) == "unset"
    assert refusal("design/boards", state) == "not_absolute"
    assert refusal(str(tmp_path / "nowhere"), state) == "missing"
    plain = tmp_path / "plain.txt"
    plain.write_text("x")
    assert refusal(str(plain), state) == "not_a_folder"
    link = tmp_path / "link"
    link.symlink_to(env.root)
    assert refusal(str(link), state) == "symlink"
    assert refusal(str(link / "x"), state) == "missing"
    above = tmp_path / "linked-parent"
    above.symlink_to(env.root.parent)
    assert refusal(str(above / "boards"), state) == "symlink"
    unmarked = tmp_path / "repo" / "unmarked"
    unmarked.mkdir()
    assert refusal(str(unmarked), state) == "no_marker"
    no_git = tmp_path / "loose" / "boards"
    no_git.mkdir(parents=True)
    (no_git / ".boards-root").write_text("m")
    assert refusal(str(no_git), state) == "no_checkout"


def test_the_state_folder_the_app_copy_and_an_app_bundle_are_refused(env: Env, tmp_path: Path):
    state = env.host.state_dir
    for parent in (state / "cplugs" / "reviewboard", tmp_path / "repo" / "Carnivore Menubar", tmp_path / "repo" / "Carnivore.app" / "Contents"):
        folder = parent / "boards"
        folder.mkdir(parents=True)
        (folder / ".boards-root").write_text("m")
        assert refusal(str(folder), state) == "forbidden", parent
    (state / ".git").mkdir()
    inside = state / "boards"
    inside.mkdir()
    (inside / ".boards-root").write_text("m")
    assert refusal(str(inside), state) == "forbidden"


def test_a_linked_worktree_counts_as_a_checkout(env: Env, tmp_path: Path):
    worktree = tmp_path / "wt"
    (worktree / "design" / "boards").mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere\n")
    (worktree / "design" / "boards" / ".boards-root").write_text("m")
    assert board_root.check_root(str(worktree / "design" / "boards"), env.host.state_dir)


def test_the_root_route_says_why(env: Env, client):
    assert client.get(f"{BASE}/root").json() == {"ok": True, "path": str(env.root), "default": False}
    (env.root.parent.parent / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (env.root.parent.parent / ".git" / "config").write_text("[core]\n")
    warned = client.get(f"{BASE}/root").json()
    assert warned["ok"] is True and [w["code"] for w in warned["warnings"]] == ["no_commits", "no_remote"]
    (env.root.parent.parent / ".git" / "HEAD").unlink()
    (env.root.parent.parent / ".git" / "config").unlink()
    env.set_root(env.root.parent)
    body = client.get(f"{BASE}/root").json()
    assert body["ok"] is False and body["reason"] == "no_marker" and "marker" in body["message"]



def test_the_list_is_newest_activity_first_and_filters_by_task(env: Env, client):
    make_board(env.root)
    second_board(env)
    listed = client.get(f"{BASE}/boards").json()
    assert [b["slug"] for b in listed["boards"]] == ["20261014-side-panel", "20261013-bottom-bar"]
    assert listed["clean"] is True and listed["problems"] == []
    first = listed["boards"][1]
    assert first["title"] == "bottom bar" and first["revisions"] == 1 and first["rounds"] == 1 and first["latest"] == "r001.html"
    assert first["task"] == {"item_id": 526, "computer": "mac-mini-m4", "github_issue": "Harbor666/CarnivoreAIDev#1700"}
    assert first["state"] == "with_claude" and len(first["etag"]) == 64
    only = client.get(f"{BASE}/boards", params={"task": 530}).json()["boards"]
    assert [b["slug"] for b in only] == ["20261014-side-panel"]
    assert client.get(f"{BASE}/boards", params={"task": 0}).status_code == 422


def test_an_empty_folder_is_an_empty_list_and_a_broken_board_is_a_problem(env: Env, client):
    assert client.get(f"{BASE}/boards").json() == {"boards": [], "problems": [], "clean": True}
    folder = make_board(env.root)
    (folder / "r001.html").write_text("changed after the fact")
    listed = client.get(f"{BASE}/boards").json()
    assert listed["clean"] is False and listed["boards"][0]["status"] == "invalid"
    assert [p["code"] for p in listed["problems"]] == ["hash_mismatch"]


def test_one_board_in_full_without_html(env: Env, client):
    folder = make_board(env.root)
    answer = client.get(f"{BASE}/boards/20261013-bottom-bar").json()
    assert answer["status"] == "ok" and answer["revision_dir"] == str(folder)
    assert answer["sidecar"]["revisions"][0]["views"][0]["file"] == "r001.html"
    assert answer["sidecar"]["rounds"][0]["note"] == "closer, keep going"
    assert "<!doctype" not in str(answer)
    assert client.get(f"{BASE}/boards/20261013-nope").status_code == 404
    assert client.get(f"{BASE}/boards/not-a-slug").json()["detail"]["code"] == "reviewboard_not_found"


def test_a_board_from_a_newer_build_is_shown_raw_and_read_only(env: Env, client):
    folder = make_board(env.root)
    raw = sidecar()
    raw["schema_version"] = 9
    (folder / "sidecar.json").write_text(__import__("json").dumps(raw))
    answer = client.get(f"{BASE}/boards/20261013-bottom-bar").json()
    assert answer["status"] == "newer" and answer["sidecar"]["schema_version"] == 9


def test_the_routes_refuse_while_off_or_without_a_usable_folder(env: Env, client):
    env.set_root(env.root.parent)
    for path in ("/boards", "/boards/20261013-bottom-bar"):
        r = client.get(f"{BASE}{path}")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_no_root" and r.json()["detail"]["reason"] == "no_marker"
    assert client.post(f"{BASE}/rescan").status_code == 409
    env.set_root(None)
    assert client.get(f"{BASE}/boards").json()["boards"] == []
    from src.cplugs.host import runtime, state as owner_state
    from dataclasses import replace
    owner_state.update(env.host.state_dir, runtime.find("reviewboard").manifest, None, lambda st: replace(st, enabled=False))
    off = client.get(f"{BASE}/boards")
    assert off.status_code == 409 and off.json()["detail"]["code"] == "cplug_disabled"


def test_a_rescan_reads_again_and_names_the_topic(env: Env, client):
    assert client.post(f"{BASE}/rescan").json()["boards"] == []
    make_board(env.root)
    answer = client.post(f"{BASE}/rescan").json()
    assert [b["slug"] for b in answer["boards"]] == ["20261013-bottom-bar"]
    assert env.published == ["cplug.reviewboard.boards", "cplug.reviewboard.boards"]



def test_the_two_read_tools_list_and_get(env: Env):
    make_board(env.root)
    second_board(env)
    ok, listed = env.call("task_manager_boards_list", {})
    assert ok and [b["slug"] for b in listed["boards"]] == ["20261014-side-panel", "20261013-bottom-bar"]
    ok, filtered = env.call("task_manager_boards_list", {"task": 526})
    assert ok and [b["slug"] for b in filtered["boards"]] == ["20261013-bottom-bar"]
    ok, one = env.call("task_manager_board_get", {"board": "20261013-bottom-bar"})
    assert ok and one["revision_dir"].endswith("20261013-bottom-bar") and len(one["sidecar"]["rounds"]) == 1
    ok, later = env.call("task_manager_board_get", {"board": "20261013-bottom-bar", "since_round": 1})
    assert ok and later["sidecar"]["rounds"] == [] and later["sidecar"]["revisions"][0]["id"] == "r1"
    ok, text = env.call("task_manager_board_get", {"board": "20261013-missing"})
    assert not ok and "reviewboard_not_found" in text
    ok, text = env.call("task_manager_board_get", {})
    assert not ok and "board is required" in text
    ok, text = env.call("task_manager_boards_list", {"task": "x"})
    assert not ok and "task must be an item id" in text


def test_the_tools_say_why_when_the_folder_is_unusable(env: Env):
    env.set_root(env.root.parent)
    ok, text = env.call("task_manager_boards_list", {})
    assert not ok and "reviewboard_no_root" in text and "marker" in text


def test_a_read_token_sees_the_read_tools_and_a_disabled_plugin_hides_them(env: Env):
    read = {d["name"] for d in tools.tool_definitions(AgentCaller("x", "x", "x", "tok", "read"))}
    assert {"task_manager_boards_list", "task_manager_board_get"} <= read
    from src.cplugs.host import runtime, state as owner_state
    from dataclasses import replace
    owner_state.update(env.host.state_dir, runtime.find("reviewboard").manifest, None, lambda st: replace(st, enabled=False))
    assert not {d["name"] for d in tools.tool_definitions()} & {"task_manager_boards_list", "task_manager_board_get"}



def test_the_federation_board_route_does_not_admit_the_task_manager_family():
    principal = SimpleNamespace(is_peer=True, grant=SimpleNamespace(peer_install_id="abcdef1234567890"))
    body = BoardBody(project_uid="project-uid-1", args={})
    with pytest.raises(Exception) as caught:
        asyncio.run(board_verb("task_manager_boards_list", body, request=None, principal=principal))
    assert caught.value.status_code == 409 and caught.value.detail == {"code": "tool_not_proxied"}



def test_board_state_follows_whose_turn_it_is():
    from src.cplugs.reviewboard import document, state
    parse = lambda raw: document.parse_sidecar(raw)  # noqa: E731
    raw = sidecar()
    assert state.board_state(parse(raw)) == state.WITH_CLAUDE
    rev2 = copy.deepcopy(raw["revisions"][0])
    rev2.update(id="r2", n=2, created_at="2026-10-13T15:00:00Z", answers_round="n1")
    rev2["views"][0]["file"] = "r002.html"
    raw["revisions"].append(rev2)
    assert state.board_state(parse(raw)) == state.YOUR_TURN
    fresh = sidecar(rounds=[])
    assert state.board_state(parse(fresh)) == state.YOUR_TURN
    assert state.board_state(parse(sidecar(revisions=[], rounds=[]))) == state.EMPTY
    lost = sidecar()
    lost["rounds"][0]["delivery"] = {"state": "undelivered", "reason": "huddle off"}
    assert state.board_state(parse(lost)) == state.UNDELIVERED
