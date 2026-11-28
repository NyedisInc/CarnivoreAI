
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.crosstalk import spawn, spawn_remote
from src.core.mcp import beast_mode, place_args, tools, write_tools
from src.core.mcp.approvals import display
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.pack.jobs import agent_facts, boot, place, policy as policy_mod
from src.core.pack.jobs.agent_facts import CallerFacts
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS, JobError
from src.core.pack.placement import rule
from src.core.pack.reserve.holds import HOLDS
from src.core.pack.session_place import create as create_mod, decide as decide_mod
from src.core.pack.session_place.types import CAP_SESSION_PLACE
from src.core.pack.session_place.wire import PeerCreateAnswer

UID = "p1x23456"
A, B, C = "iid-a", "iid-b", "iid-c"
HEAD = "a" * 40
CAPS = [CAP_JOBS, CAP_SESSION_PLACE]
CALLER = AgentCaller("ses_c", "cloude_c", "ses_c")


def snap(load1: float) -> Dict[str, Any]:
    return {"load": {"cores": 10, "load_1": load1, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "restrictions": {"may_host_agents": True},
            "can": {"tools": {"claude": True}, "xcode": False, "brew": False}}


def make_view(self_load: float, peers: Dict[str, str]) -> place.PlaceView:
    me = rule.MachineInput(A, "nostromo", snap(self_load), True, True, True, True, 0)
    ps = [rule.MachineInput(iid, label, snap(0.5), True, False, False, True, None) for iid, label in peers.items()]
    return place.PlaceView(me, ps, {p.install_id: list(CAPS) for p in ps}, A)


class World:

    def __init__(self, store: JobStore, tmp: Path) -> None:
        self.store, self.view, self.tmp = store, make_view(1.0, {}), tmp
        self.posts: List[Any] = []
        self.script: Dict[str, Any] = {}
        self.local: List[Any] = []
        self.parks: List[Dict[str, Any]] = []
        self.live: set = set()
        self.beast = False
        self.permissions: Any = None


@pytest.fixture()
def world(tmp_path: Path, monkeypatch) -> World:
    HOLDS._entries.clear()
    write_tools._created.clear()
    write_tools._reserved.clear()
    w = World(JobStore(tmp_path / "state"), tmp_path)
    policy_mod.set_auto(w.store, UID, True)
    monkeypatch.setitem(boot._built, "engine", SimpleNamespace(store=w.store, _view_for=lambda root, uid: w.view))
    monkeypatch.setattr(decide_mod, "_project_of", lambda req, eng: (UID, "app", str(tmp_path)))
    monkeypatch.setattr(decide_mod, "_copies", lambda eng, uid: {B: "/w/app-b", C: "/w/app-c"})
    monkeypatch.setattr(create_mod, "_project", lambda name: {"uid": UID, "display_name": name, "root": str(tmp_path)})
    monkeypatch.setattr(create_mod, "_git_facts", lambda root: (HEAD, "main", 2))
    monkeypatch.setattr(create_mod, "_peer", lambda iid: SimpleNamespace(key=f"peer-{iid[-1]}", label=iid, peer_install_id=iid))

    async def carry(project: Dict[str, Any], install_id: str, label: str) -> Dict[str, Any]:
        return {"machine": label, "sent": True}

    async def post(install_id: str, label: str, body: Any) -> PeerCreateAnswer:
        w.posts.append((install_id, body))
        got = w.script.get(install_id)
        if isinstance(got, Exception):
            raise got
        return PeerCreateAnswer(session_id="ses_far", session_uuid="u-far", tmux_name=f"carnivore_{install_id[-1]}", working_dir="/w/app-b",
                                account_label="work", account_how="relay", profile_used="default")

    async def local(request: Any, body: Any) -> Any:
        w.local.append(body)
        return SimpleNamespace(id="ses_local1", working_dir=body.working_dir)

    async def park(manager, caller, tid, tmux, action, summary, shown, run, *rest, **kw) -> dict:
        w.parks.append({"action": action, "summary": summary, "shown": shown, "kw": kw})
        return await run(True)

    async def unprompted(caller, action, run, **kw) -> dict:
        w.parks.append({"action": action, "beast": True, "shown": kw.get("args")})
        return await run()

    async def facts(app, session) -> CallerFacts:
        return CallerFacts("claude", "work", "default")

    async def infos() -> list:
        return [SimpleNamespace(session=SimpleNamespace(id="ses_c"), host_key="local", label=None, claude_title=None, tmux_session="", session_uuid="u-c", launched_with=w.permissions and {"permissions": w.permissions})]

    monkeypatch.setattr(create_mod, "_carry", carry)
    monkeypatch.setattr(create_mod, "_post", post)
    monkeypatch.setattr("src.api.session_crud_routes.create_session", local)
    monkeypatch.setattr(write_tools, "park", park)
    monkeypatch.setattr(beast_mode, "run_unprompted", unprompted)
    monkeypatch.setattr(beast_mode, "approval_skip", lambda action: w.beast)
    monkeypatch.setattr(agent_facts, "caller_launch_facts", facts)
    manager = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=SimpleNamespace(list_session_infos=infos))),
                              live_ids_now=lambda: asyncio.sleep(0, result=set(w.live)))
    w.manager = manager
    yield w
    HOLDS._entries.clear()
    write_tools._created.clear()
    write_tools._reserved.clear()


def create(w: World, **args: Any) -> Dict[str, Any]:
    return asyncio.run(write_tools.session_create(w.manager, CALLER, {"working_dir": str(w.tmp), **args}))


def payload(out: Dict[str, Any]) -> Dict[str, Any]:
    import json

    return json.loads(out["content"][0]["text"])


def card(w: World, index: int = -1) -> Dict[str, Any]:
    p = w.parks[index]
    return display.build(p["action"], p["shown"], "", p["summary"])


def lines(c: Dict[str, Any]) -> List[str]:
    return [f"{x['key']} {x['params']}" for x in c["consequences"]]


def test_placement_with_peer_account_or_bad_needs_is_refused_before_anything_is_asked(world):
    for bad in ({"placement": "auto", "peer": "tower"}, {"placement": "auto", "account": "work"}, {"needs": ["xcode"]},
                {"placement": "elsewhere"}, {"placement": "auto", "needs": ["x"] * 9}, {"placement": "auto", "needs": [""]}, {"posture": "skip_all"}):
        with pytest.raises(ToolError):
            create(world, **bad)
    assert not world.parks and not world.posts and not world.local


def test_default_placement_is_untouched_and_a_card_without_placement_stays_generic(world):
    out = create(world)
    assert out["content"] and world.local and not world.posts
    assert "placement" not in world.parks[0]["shown"]
    assert display.build("session_create", world.parks[0]["shown"], "", world.parks[0]["summary"])["verb"] == "session create"


def test_a_pegged_computer_card_names_the_computer_and_the_create_goes_there(world):
    world.view = make_view(9.8, {B: "tower"})
    out = create(world, placement="auto", name="trader")
    park = world.parks[0]
    assert park["action"] == "session_create" and "tower" in park["summary"] and park["summary"].startswith("create a session in ")
    c = card(world)
    assert c["tone"] == "confirm" and c["consequences"][0]["key"] == "place_remote" and c["consequences"][0]["params"]["computer"] == "tower"
    assert [p[0] for p in world.posts] == [B] and not world.local
    got = payload(out)
    assert got["id"] == "remote:peer-b:carnivore_b" and got["placement"]["decision"] == "remote" and got["placement"]["label"] == "tower"


def test_card_is_the_contract_computer_account_and_posture_are_what_the_peer_body_carries(world):
    world.view = make_view(9.8, {B: "tower"})
    world.permissions = "accept_edits"
    create(world, placement="auto")
    shown = world.parks[0]["shown"]
    to, body = world.posts[0]
    assert to == B and shown["computer"] == "tower"
    assert shown["account"] == body.account_key == "work" and shown["posture"] == body.posture == "accept_edits"
    keys = [x["key"] for x in card(world)["consequences"]]
    assert keys == ["place_remote", "place_account", "place_mode_edits"] and card(world)["consequences"][1]["params"]["account"] == body.account_key
    assert shown["posture"] != "skip_all"


def test_unknown_posture_is_sent_as_unknown_and_never_from_an_argument(world):
    world.view = make_view(9.8, {B: "tower"})
    create(world, placement="auto")
    assert world.posts[0][1].posture == "unknown" and world.parks[0]["shown"]["posture"] == "unknown"
    assert card(world)["consequences"][2]["key"] == "place_mode_unknown"
    with pytest.raises(ToolError):
        create(world, placement="auto", posture="skip_all")


def test_skip_all_travels_only_from_the_launch_record_and_the_card_warns(world):
    world.view = make_view(9.8, {B: "tower"})
    world.permissions = "skip_all"
    create(world, placement="auto")
    c = card(world)
    assert world.posts[0][1].posture == "skip_all" and c["tone"] == "danger"
    assert c["consequences"][2]["key"] == "delegate_mode_bypass" and c["consequences"][2]["params"]["computer"] == "tower"


def test_a_refusal_after_approval_starts_here_with_both_reasons_and_asks_no_other_computer(world):
    world.view = make_view(9.8, {B: "tower", C: "mini"})
    world.script[B] = JobError("copy_not_ready", "tower's copy has changes of its own", 409)
    out = create(world, placement="auto")
    named = world.parks[0]["shown"]["computer"]
    assert [p[0] for p in world.posts] == [B] and named == "tower"
    assert len(world.local) == 1 and "ses_local1" in str(out)
    block = payload(out)["placement"]
    assert block["decision"] == "here" and "tower refused" in block["reason"]
    assert block["reasons"][0] == world.parks[0]["shown"]["reason"] and "tower refused" in block["reasons"][1] and "launch" in payload(out)


def test_strict_need_nobody_meets_refuses_with_nothing_parked(world):
    world.view = make_view(1.0, {B: "tower"})
    with pytest.raises(ToolError, match="requirement"):
        create(world, placement="auto", needs=["xcode"])
    assert not world.parks and not world.posts and not world.local


def test_this_computer_with_room_parks_a_here_card_and_creates_locally(world):
    world.view = make_view(1.0, {B: "tower"})
    create(world, placement="auto")
    c = card(world)
    assert c["consequences"][0]["key"] == "place_here" and len(c["consequences"]) == 1 and len(world.local) == 1 and not world.posts


def test_caps_count_a_placed_session_five_per_agent_and_twenty_in_all(world):
    world.view = make_view(9.8, {B: "tower"})
    create(world, placement="auto")
    assert write_tools._created["remote:peer-b:carnivore_b"][0] == "cloude_c"
    for i in range(4):
        write_tools._created[f"ses_x{i}"] = ("cloude_c", time.monotonic())
    world.live = set(write_tools._created)
    world.posts.clear()
    with pytest.raises(ToolError, match="limit 5"):
        create(world, placement="auto")
    assert not world.posts
    write_tools._created.clear()
    for i in range(20):
        write_tools._created[f"ses_y{i}"] = (f"cloude_{i}", time.monotonic())
    world.live = set(write_tools._created)
    with pytest.raises(ToolError, match="limit 20"):
        create(world, placement="auto")
    assert not world.posts and write_tools._reserved == []


def test_beast_armed_runs_the_placed_create_unprompted(world):
    world.view = make_view(9.8, {B: "tower"})
    world.beast = True
    create(world, placement="auto")
    assert world.parks[0].get("beast") is True and [p[0] for p in world.posts] == [B]


def test_the_two_tool_descriptions_and_schemas_stay_inside_the_budget():
    by_name = {d["name"]: d for d in tools.tool_definitions(None)}
    for name in ("session_create", "agent_spawn"):
        assert len(by_name[name]["description"]) <= 400
        props = by_name[name]["inputSchema"]["properties"]
        assert props["placement"]["enum"] == ["here", "auto"] and props["needs"]["maxItems"] == 8


def spawn_body(**kw: Any) -> spawn.SpawnRequest:
    return spawn.SpawnRequest.model_validate({"provider": "claude", "task": "do it", **kw})


def test_spawn_request_rules_for_auto():
    assert spawn_body().placement == "here" and spawn_body().needs == []
    for bad in ({"needs": ["xcode"]}, {"placement": "auto", "peer": "tower"}, {"placement": "auto", "needs": ["x"] * 9}):
        with pytest.raises(ValueError):
            spawn_body(**bad)
    assert "placement" not in spawn_body().model_dump(exclude_none=True, exclude={"placement", "needs"})


def prepare(w: World, **kw: Any) -> spawn_remote.AutoPlan:
    view = SimpleNamespace(app=w.manager.app)
    return asyncio.run(spawn_remote.prepare_auto(view, CALLER, spawn_body(placement="auto", **kw), str(w.tmp)))


def test_spawn_auto_with_worktree_or_effort_stays_here_and_asks_nobody(world, monkeypatch):
    world.view = make_view(9.8, {B: "tower"})

    async def never(*a: Any, **k: Any) -> None:
        raise AssertionError("a create that cannot leave is not placed")

    monkeypatch.setattr(decide_mod, "decide", never)
    got = prepare(world, worktree=True)
    assert got.plan.decision == "here" and got.plan.reason == "a new worktree stays on this computer"
    assert prepare(world, effort="high").plan.decision == "here"


def test_spawn_auto_decides_remote_when_pegged_and_its_card_names_the_computer(world):
    world.view = make_view(9.8, {B: "tower"})
    world.permissions = "skip_all"
    got = prepare(world, model="claude-opus-4-1")
    assert (got.plan.decision, got.plan.label, got.starter.posture, got.starter.account_key, got.starter.model) == ("remote", "tower", "skip_all", "work", "claude-opus-4-1")
    shown = place_args.card_args(got.plan, got.starter, {"provider": "claude"})
    c = display.build("agent_spawn", shown, "", place_args.summary_of(got.plan, "spawn claude"))
    assert c["tone"] == "danger" and c["consequences"][0]["params"]["computer"] == "tower" and c["consequences"][2]["key"] == "delegate_mode_bypass"


def test_spawn_auto_remote_runs_the_post_steps_once_on_the_named_computer(world, monkeypatch):
    from src.core.crosstalk import bus, spawn_layout
    from src.core.federation import peer_listing, shadow_rows
    from src.core.flow_data import spawn_links
    from src.core import session_change_notice
    from src.core.mcp import federated

    world.view = make_view(9.8, {B: "tower"})
    parent = SimpleNamespace(session=SimpleNamespace(id="ses_c", tmux_created_epoch=1), tmux_session="cloude_c", session_uuid="u-c", session_row_id=1)
    child = SimpleNamespace(session=SimpleNamespace(id="remote:peer-b:carnivore_b", tmux_created_epoch=9), session_uuid=shadow_rows.shadow_uuid(B, "u-far"))
    sent: List[Any] = []

    class View:
        app = world.manager.app

        def fresh(self) -> "View":
            return self

        async def list_session_infos(self) -> list:
            return [parent]

        async def live_ids_now(self) -> set:
            return set()

    async def refresh(*a: Any, **k: Any) -> None:
        return None

    async def peer_infos(force: bool = False) -> list:
        return [child]

    async def send(view: Any, caller: Any, **kw: Any) -> Dict[str, Any]:
        sent.append(kw)
        return {"id": "m1"}

    async def persist(*a: Any) -> str:
        return "appended"

    monkeypatch.setattr(peer_listing, "refresh", refresh)
    monkeypatch.setattr(federated, "peer_infos", peer_infos)
    monkeypatch.setattr(bus, "send", send)
    monkeypatch.setattr(spawn_layout, "persist", persist)
    monkeypatch.setattr(spawn_links, "record_quietly", lambda **k: None)
    monkeypatch.setattr(session_change_notice, "publish", lambda *a, **k: None)
    view = View()
    out = asyncio.run(spawn.spawn(view, CALLER, spawn_body(placement="auto", working_dir=str(world.tmp)), owner_approved=False))
    assert [p[0] for p in world.posts] == [B] and not world.local
    assert out["id"] == "remote:peer-b:carnivore_b" and out["placement"]["decision"] == "remote" and sent[0]["to"] == out["id"]
    assert write_tools._created[out["id"]][0] == "cloude_c" and write_tools._reserved == []
    assert world.parks[0]["action"] == "agent_spawn" and world.parks[0]["shown"]["computer"] == "tower"


def test_a_repeat_auto_call_refreshes_the_one_card_even_when_the_load_figure_moved(world):
    world.view = make_view(9.8, {B: "tower"})
    create(world, placement="auto", name="trader")
    world.view = make_view(9.6, {B: "tower"})
    HOLDS._entries.clear()
    create(world, placement="auto", name="trader")
    first, second = world.parks[0], world.parks[1]
    assert first["kw"]["dedupe_key"] == second["kw"]["dedupe_key"] and first["kw"]["supersede"] is True
    create(world, placement="auto", name="other")
    assert world.parks[2]["kw"]["dedupe_key"] != first["kw"]["dedupe_key"]


def test_a_marked_projects_session_create_defaults_to_auto_and_an_explicit_choice_wins(world, monkeypatch):
    monkeypatch.setattr(place_args, "marked_folder", lambda folder: True)
    world.view = make_view(9.8, {B: "tower"})
    out = create(world)
    assert world.parks[0]["shown"]["placement"] == "auto" and [p[0] for p in world.posts] == [B] and not world.local and payload(out)["placement"]["decision"] == "remote"
    world.parks.clear(), world.posts.clear()
    create(world, placement="here")
    assert "placement" not in world.parks[0]["shown"] and world.local and not world.posts
    world.parks.clear(), world.local.clear()
    monkeypatch.setattr(place_args, "marked_folder", lambda folder: (_ for _ in ()).throw(AssertionError("an account never defaults")))
    with pytest.raises(ToolError):
        create(world, account="work", placement="auto")
    world.view = make_view(1.0, {B: "tower"})
    monkeypatch.setattr(place_args, "marked_folder", lambda folder: True)
    create(world)
    assert world.local and not world.posts


def test_an_unmarked_or_unreadable_project_keeps_here(world):
    assert place_args.marked_folder(str(world.tmp)) is False
    create(world)
    assert "placement" not in world.parks[0]["shown"]


def test_agent_spawn_defaults_to_auto_in_a_marked_project_and_explicit_here_or_peer_wins(world, monkeypatch):
    seen: List[str] = []

    async def prepare_auto(view, caller, body, folder):
        seen.append(body.placement)
        raise ToolError("reached placement")

    async def park(manager, caller, tid, tmux, action, summary, shown, run, *rest, **kw):
        seen.append(shown.get("placement", "here"))
        return {"parked": True}

    parent = SimpleNamespace(session=SimpleNamespace(id="ses_c", tmux_created_epoch=1, working_dir=str(world.tmp)), tmux_session="cloude_c")

    class View:
        async def list_session_infos(self):
            return [parent]

    monkeypatch.setattr(spawn_remote, "prepare_auto", prepare_auto)
    monkeypatch.setattr(write_tools, "park", park)

    def go(**kw):
        return asyncio.run(spawn.spawn(View(), CALLER, spawn_body(working_dir=str(world.tmp), **kw)))

    monkeypatch.setattr(place_args, "marked_folder", lambda folder: True)
    with pytest.raises(ToolError, match="reached placement"):
        go()
    assert seen == ["auto"]
    seen.clear()
    assert go(placement="here") == {"parked": True} and seen == ["here"]
    monkeypatch.setattr(place_args, "marked_folder", lambda folder: False)
    assert go() == {"parked": True} and seen == ["here", "here"]


def test_a_brief_naming_a_file_edited_here_keeps_the_agent_here_and_an_unrelated_one_goes_auto(world, monkeypatch):
    from src.core.pack.session_place import same_file

    dirty = ["web/src/App.svelte", "src/core/a/util.py", "src/core/b/util.py", "docs/notes.md"]
    monkeypatch.setattr(same_file, "dirty_of", lambda folder: dirty)
    world.view = make_view(9.8, {B: "tower"})
    for brief, hit in (("fix the layout in web/src/App.svelte", "web/src/App.svelte"), ("change App.svelte colors", "web/src/App.svelte"),
                       ("tidy util.py", "src/core/a/util.py"), ("rework everything under src/core/b", "src/core/b/")):
        got = prepare(world, task=brief)
        assert got.plan.decision == "here" and got.plan.reason == f"{hit} is being edited on this computer", brief
    unrelated = prepare(world, task="write a new parser in src/core/c/parse.py and notes about Apple")
    assert unrelated.plan.decision == "remote" and unrelated.plan.label == "tower"
    monkeypatch.setattr(same_file, "dirty_of", lambda folder: (_ for _ in ()).throw(JobError("not_a_repo", "x", 409)))
    assert prepare(world, task="edit web/src/App.svelte").plan.decision == "remote"


def test_clash_is_pure_and_matches_whole_words_only():
    from src.core.pack.session_place.same_file import clash

    assert clash("edit /Users/a/app/src/x.py please", ["src/x.py"]) == "src/x.py"
    assert clash("edit xsrc/z.py", ["src/x.py"]) is None and clash("see ax.py", ["src/x.py"]) is None
    assert clash("anything", []) is None
