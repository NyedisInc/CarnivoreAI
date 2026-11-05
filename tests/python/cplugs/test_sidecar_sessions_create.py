
from __future__ import annotations

import asyncio
import functools
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

from src.core.mcp import pending, write_tools
from src.cplugs.host import capabilities, session_create_launch as launch_mod, session_create_port, sidecar_boot, sideload
from src.cplugs.host.session_create_port import SessionCreatePort, standing_of
from src.cplugs.runtime import guards
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens


def run_async(fn):
    @functools.wraps(fn)
    def runner(*args: Any, **kwargs: Any) -> None:
        asyncio.run(fn(*args, **kwargs))

    return runner


PROJECT: Dict[str, Any] = {"id": 7, "name": "Flow", "path": "/work/flow", "default_launch_profile": None}


class World:

    def __init__(self) -> None:
        self.project: Optional[Dict[str, Any]] = dict(PROJECT)
        self.skips = False
        self.standing = ""
        self.now = 1000.0
        self.made: List[Dict[str, Any]] = []
        self.start_error: Optional[Exception] = None

    def resolve(self, project: Dict[str, Any], family: Optional[str]) -> launch_mod.Launch:
        path = str(project["path"])
        return launch_mod.Launch(project=project["name"], working_dir=path, where=launch_mod._where(path),
                                 agent_type=family or "claude", profile_id="claude-default", profile_label="Claude default",
                                 permissions="skip_all" if self.skips else "harness_default",
                                 badge="skips all permission checks" if self.skips else "harness default", custom_command=False)

    async def start(self, request: Any, project_id: int, *, opening_prompt: Optional[str] = None, agent_type: Optional[str] = None) -> str:
        if self.start_error is not None:
            raise self.start_error
        self.made.append({"project": project_id, "prompt": opening_prompt, "agent_type": agent_type})
        return f"ses_fake{len(self.made)}"

    async def live(self) -> set:
        return {f"ses_fake{i + 1}" for i in range(len(self.made))}


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch):
    world = World()
    monkeypatch.setattr(capabilities, "Projects", lambda: SimpleNamespace(get=lambda pid: dict(world.project) if world.project and pid == 7 else None))
    monkeypatch.setattr(launch_mod, "resolve", world.resolve)
    monkeypatch.setattr(write_tools, "_created", {})
    store = pending.PendingActions()
    port = SessionCreatePort(object(), store=store, wait_seconds=2.0, start=world.start, standing=lambda pid: world.standing,
                             live_ids=world.live, clock=lambda: world.now)
    services = HostServices(activity=lambda entry: None, create_session=port.create)
    return port, store, world, HostDispatcher(services, OwnerTokens())


def _ctx(tier: str = "local", granted: frozenset = frozenset({"sessions.create"})) -> PluginContext:
    return PluginContext(plugin_id="local/flow", install_key="k1", data_dir=Path("/nonexistent"), granted=granted, tier=tier)


async def _owner(store: pending.PendingActions, decision: str, *, after: float = 0.05) -> None:
    for _ in range(100):
        rows = store.list()
        if rows:
            await asyncio.sleep(after)
            if decision == "approve":
                await store.approve(rows[0]["id"])
            else:
                store.deny(rows[0]["id"])
            return
        await asyncio.sleep(0.02)


async def _ask(dispatcher: HostDispatcher, **over: Any) -> Any:
    return await dispatcher.handle(_ctx(), "sessions.create", {**ARGS, **over})


async def _parked(store: pending.PendingActions, count: int = 1) -> None:
    for _ in range(100):
        if len(store.list()) >= count:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("no card was parked")


ARGS = {"project": 7, "prompt": "map the billing flow", "family": "claude"}


@run_async
async def test_sideload_with_grant_waits_for_approval_and_creates_exactly_one(rig) -> None:
    _port, store, world, dispatcher = rig
    call = asyncio.create_task(_ask(dispatcher))
    await asyncio.sleep(0.2)
    assert world.made == [] and len(store.list()) == 1
    assert store.list()[0]["action"] == "plugin_session_create"
    await _owner(store, "approve")
    assert await call == {"ref": "ses_fake1"}
    assert world.made == [{"project": 7, "prompt": "map the billing flow", "agent_type": "claude"}]


@run_async
async def test_denial_is_final_and_creates_nothing(rig) -> None:
    _port, store, world, dispatcher = rig
    owner = asyncio.create_task(_owner(store, "deny"))
    with pytest.raises(guards.Refused) as caught:
        await _ask(dispatcher)
    await owner
    assert (caught.value.code, caught.value.data["reason"]) == ("permission_denied", "owner_denied") and world.made == []


@run_async
async def test_timeout_withdraws_the_card_and_a_late_approve_creates_nothing(rig) -> None:
    port, store, world, dispatcher = rig
    port._wait = 0.2
    task = asyncio.create_task(_ask(dispatcher))
    await _parked(store)
    card_id = store.list()[0]["id"]
    with pytest.raises(guards.Refused) as caught:
        await task
    assert (caught.value.code, caught.value.data["reason"]) == ("timeout", "owner_timeout")
    with pytest.raises(ValueError, match="already denied"):
        await store.approve(card_id)
    assert world.made == [] and store.list() == []


@run_async
async def test_a_cancelled_wait_withdraws_the_card_so_a_late_approve_creates_nothing(rig) -> None:
    _port, store, world, dispatcher = rig
    task = asyncio.create_task(_ask(dispatcher))
    await _parked(store)
    card_id = store.list()[0]["id"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.list() == []
    with pytest.raises(ValueError, match="already denied"):
        await store.approve(card_id)
    assert world.made == []


@run_async
async def test_a_revoked_grant_refuses_the_approve_and_creates_nothing(rig) -> None:
    _port, store, world, dispatcher = rig
    for slug in ("grant_revoked", "not_running", "not_a_sideload", "sideload_off"):
        world.standing = ""
        task = asyncio.create_task(_ask(dispatcher))
        await _parked(store)
        world.standing = slug
        card = store.list()[0]
        item = await store.approve(card["id"])
        assert item.status == pending.REFUSED
        with pytest.raises(guards.Refused) as caught:
            await task
        assert (caught.value.code, caught.value.data["reason"]) == ("permission_denied", "not_standing")
    assert world.made == []


@run_async
async def test_a_changed_folder_or_launch_refuses_the_approve(rig) -> None:
    _port, store, world, dispatcher = rig
    for change in ("moved", "skips"):
        world.project, world.skips = dict(PROJECT), False
        task = asyncio.create_task(_ask(dispatcher))
        await _parked(store)
        if change == "moved":
            world.project["path"] = "/work/elsewhere"
        else:
            world.skips = True
        assert (await store.approve(store.list()[0]["id"])).status == pending.REFUSED
        with pytest.raises(guards.Refused) as caught:
            await task
        assert caught.value.data["reason"] == "launch_changed"
    assert world.made == []


@run_async
async def test_the_card_face_shows_what_will_run(rig) -> None:
    _port, store, world, dispatcher = rig
    long_prompt = "write the report. " * 400 + "‮end\nnext line"
    task = asyncio.create_task(_ask(dispatcher, prompt=long_prompt, family=None))
    await _parked(store)
    display = store.list()[0]["display"]
    assert (display["verb"], display["object"], display["name"], display["tone"]) == ("start", "session", "local/flow", "confirm")
    keys = [c["key"] for c in display["consequences"]]
    assert keys == ["plugin_project", "plugin_agent", "plugin_prompt"]
    project, agent, prompt = (c["params"] for c in display["consequences"])
    assert (project["project"], project["where"]) == ("Flow", "/work/flow")
    assert (agent["agent"], agent["profile"]) == ("claude", "Claude default")
    assert prompt["prompt"] == json.dumps(guards.strip_invisible(long_prompt)) and "\\n" in prompt["prompt"]
    store.deny(store.list()[0]["id"])
    with pytest.raises(guards.Refused):
        await task


@run_async
async def test_the_card_flags_a_skip_permissions_launch_and_a_paired_computer(rig) -> None:
    _port, store, world, dispatcher = rig
    world.skips = True
    world.project["path"] = "ssh://host/secret/path"
    task = asyncio.create_task(_ask(dispatcher))
    await _parked(store)
    display = store.list()[0]["display"]
    assert display["tone"] == "danger" and display["consequences"][1]["key"] == "plugin_agent_skips"
    assert display["consequences"][0]["params"]["where"] == "paired computer host"
    store.deny(store.list()[0]["id"])
    with pytest.raises(guards.Refused):
        await task


@run_async
async def test_approval_is_never_reused_for_a_second_request(rig) -> None:
    _port, store, world, dispatcher = rig
    first, second = asyncio.create_task(_ask(dispatcher)), asyncio.create_task(_ask(dispatcher))
    await _parked(store, 2)
    await store.approve(store.list()[0]["id"])
    await asyncio.sleep(0.2)
    assert len(world.made) == 1 and len(store.list()) == 1
    store.deny(store.list()[0]["id"])
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert sum(isinstance(r, dict) for r in results) == 1 and sum(isinstance(r, guards.Refused) for r in results) == 1


@run_async
async def test_catalog_plugin_is_refused_even_with_the_grant(rig) -> None:
    _port, store, world, dispatcher = rig
    before = store.version
    with pytest.raises(guards.Refused) as caught:
        await dispatcher.handle(_ctx(tier="catalog"), "sessions.create", dict(ARGS))
    assert (caught.value.code, caught.value.data["reason"]) == ("permission_denied", "sideload_only")
    assert store.version == before and world.made == []


@run_async
async def test_undeclared_capability_is_refused(rig) -> None:
    _port, store, world, dispatcher = rig
    before = store.version
    with pytest.raises(guards.Refused) as caught:
        await dispatcher.handle(_ctx(granted=frozenset()), "sessions.create", dict(ARGS))
    assert (caught.value.code, caught.value.data) == ("not_granted", {"permission": "sessions.create"})
    assert store.version == before and world.made == []


BOUNDS = [
    ({"working_dir": "/etc"}, "permission_denied", "option_not_allowed"),
    ({"argv": ["--dangerously-skip-permissions"]}, "permission_denied", "option_not_allowed"),
    ({"env": {"X": "1"}}, "permission_denied", "option_not_allowed"),
    ({"launch_profile": "yolo"}, "permission_denied", "option_not_allowed"),
    ({"family": "shell"}, "invalid_params", "bad_family"),
    ({"family": "claude --dangerously-skip-permissions"}, "invalid_params", "bad_family"),
    ({"prompt": "--dangerously-skip-permissions"}, "invalid_params", "bad_prompt"),
    ({"prompt": "update"}, "invalid_params", "bad_prompt"),
    ({"prompt": "x" * 9000}, "invalid_params", "bad_prompt"),
    ({"project": "7"}, "invalid_params", "bad_project"),
    ({"project": 999}, "not_found", "no_project"),
]


@pytest.mark.parametrize("over,code,reason", BOUNDS)
@run_async
async def test_disallowed_arguments_are_refused_before_the_owner_is_asked(rig, over, code, reason) -> None:
    _port, store, world, dispatcher = rig
    before = store.version
    with pytest.raises(guards.Refused) as caught:
        await _ask(dispatcher, **over)
    assert (caught.value.code, caught.value.data["reason"]) == (code, reason)
    assert store.version == before and store.list() == [] and world.made == []


@run_async
async def test_pending_cards_are_capped_per_plugin_and_a_stop_withdraws_them(rig) -> None:
    port, store, _world, dispatcher = rig
    port._wait = 5.0
    tasks = [asyncio.create_task(_ask(dispatcher)) for _ in range(5)]
    await _parked(store, 5)
    with pytest.raises(guards.Refused) as caught:
        await _ask(dispatcher)
    assert (caught.value.code, caught.value.data["reason"]) == ("rate_limited", "too_many_waiting")
    assert port.withdraw_for("local/flow") == 5 and store.list() == []
    for task in tasks:
        with pytest.raises(guards.Refused):
            await task
    assert port._denied_until == {}


@run_async
async def test_live_sessions_count_under_the_mcp_caps(rig) -> None:
    _port, store, world, dispatcher = rig
    for _ in range(5):
        owner = asyncio.create_task(_owner(store, "approve", after=0.0))
        await _ask(dispatcher)
        await owner
    assert len(world.made) == 5
    task = asyncio.create_task(_ask(dispatcher))
    await _parked(store)
    assert (await store.approve(store.list()[0]["id"])).status == pending.REFUSED
    with pytest.raises(guards.Refused) as caught:
        await task
    assert caught.value.data["reason"] == "cap_reached" and len(world.made) == 5


@run_async
async def test_a_denial_starts_a_cooldown_that_ends(rig) -> None:
    _port, store, world, dispatcher = rig
    owner = asyncio.create_task(_owner(store, "deny"))
    with pytest.raises(guards.Refused):
        await _ask(dispatcher)
    await owner
    before = store.version
    with pytest.raises(guards.Refused) as caught:
        await _ask(dispatcher)
    assert (caught.value.code, caught.value.data["reason"]) == ("rate_limited", "denied_recently")
    assert caught.value.data["retry_after_s"] == int(session_create_port.DENIAL_COOLDOWN_SECONDS) and store.version == before
    world.now += session_create_port.DENIAL_COOLDOWN_SECONDS + 1
    owner = asyncio.create_task(_owner(store, "approve"))
    assert await _ask(dispatcher) == {"ref": "ses_fake1"}
    await owner


@run_async
async def test_route_text_never_reaches_the_plugin(rig, caplog) -> None:
    _port, store, world, dispatcher = rig
    world.start_error = HTTPException(409, detail="working dir /Users/alex/secret/project is busy")
    owner = asyncio.create_task(_owner(store, "approve"))
    with pytest.raises(guards.Refused) as caught:
        await _ask(dispatcher)
    await owner
    assert caught.value.data == {"reason": "create_failed"}
    assert "/Users/alex" not in str(caught.value) and "/Users/alex" not in json.dumps(caught.value.data)
    assert "/Users/alex" not in json.dumps(store.decided())


@run_async
async def test_a_card_too_large_to_show_is_a_typed_refusal(rig) -> None:
    port, _store, _world, dispatcher = rig

    class Full:

        def create(self, **_: Any) -> Any:
            raise pending.PayloadTooLargeError("cannot display")

    port._store = Full()
    with pytest.raises(guards.Refused) as caught:
        await _ask(dispatcher)
    assert (caught.value.code, caught.value.data["reason"]) == ("too_large", "card_too_large")


def _fake_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, world: World) -> sidecar_boot.SidecarRuntime:
    from src.cplugs.host import runtime as host_runtime

    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    rt = sidecar_boot.SidecarRuntime(host_runtime.Host(tmp_path, None), SimpleNamespace(state=SimpleNamespace()), asyncio.get_running_loop())
    rt.session_create._store, rt.session_create._start, rt.session_create._live_ids = pending.get_store(), world.start, world.live
    return rt


@run_async
async def test_the_runtime_wires_the_port_and_checks_the_live_supervisor_at_approve(rig, monkeypatch, tmp_path) -> None:
    _port, _store, world, _dispatcher = rig
    rt = _fake_runtime(monkeypatch, tmp_path, world)
    store = pending.get_store()
    proc = SimpleNamespace(ended=None, spec=SimpleNamespace(ctx=_ctx()))
    live = {"local/flow": proc}
    monkeypatch.setattr(rt.supervisor, "process", lambda pid: live.get(pid))
    monkeypatch.setattr(sideload, "is_on", lambda state_dir: True)
    call = asyncio.create_task(rt.dispatcher.handle(_ctx(), "sessions.create", dict(ARGS)))
    await _parked(store)
    assert store.list()[0]["caller_tmux"] == "cplug:local/flow"
    live.clear()
    assert (await store.approve(store.list()[0]["id"])).status == pending.REFUSED
    with pytest.raises(guards.Refused) as caught:
        await call
    assert caught.value.data["reason"] == "not_standing" and world.made == []
    live["local/flow"] = proc
    owner = asyncio.create_task(_owner(store, "approve"))
    assert await rt.dispatcher.handle(_ctx(), "sessions.create", dict(ARGS)) == {"ref": "ses_fake1"}
    await owner
    assert rt.effects.cancel("local/flow")["inbox"] == 0


def test_standing_of_reads_process_tier_grant_and_switch(monkeypatch) -> None:
    ctx = _ctx()
    procs: Dict[str, Any] = {}
    check = standing_of(SimpleNamespace(process=procs.get), Path("."))
    monkeypatch.setattr(sideload, "is_on", lambda state_dir: True)
    assert check("local/flow") == "not_running"
    procs["local/flow"] = SimpleNamespace(ended="exited", spec=SimpleNamespace(ctx=ctx))
    assert check("local/flow") == "not_running"
    procs["local/flow"] = SimpleNamespace(ended=None, spec=SimpleNamespace(ctx=_ctx(tier="catalog")))
    assert check("local/flow") == "not_a_sideload"
    procs["local/flow"] = SimpleNamespace(ended=None, spec=SimpleNamespace(ctx=_ctx(granted=frozenset())))
    assert check("local/flow") == "grant_revoked"
    procs["local/flow"] = SimpleNamespace(ended=None, spec=SimpleNamespace(ctx=ctx))
    assert check("local/flow") == ""
    monkeypatch.setattr(sideload, "is_on", lambda state_dir: False)
    assert check("local/flow") == "sideload_off"


def _profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import settings
    from src.config.launch_profiles import LaunchProfile

    def custom(pid: str, harness: str, script: str) -> LaunchProfile:
        return LaunchProfile.model_validate({"id": pid, "label": pid, "harness": harness, "custom_command": {"script": script}})

    profiles = [custom("cx", "codex", 'codex --yolo "$@"'), custom("cl", "claude", 'claude --dangerously-skip-permissions "$@"'),
                custom("cq", "claude", 'claude --model opus "$@"'),
                LaunchProfile.model_validate({"id": "bl", "label": "bl", "harness": "claude",
                                              "before_launch": 'exec claude --dangerously-skip-permissions "$@"'}),
                LaunchProfile.model_validate({"id": "pa", "label": "pa", "harness": "claude", "env": [{"name": "PATH", "value": "/tmp/evil:/usr/bin"}]}),
                LaunchProfile.model_validate({"id": "ev", "label": "ev", "harness": "claude", "env": [{"name": "FOO", "value": "1"}]}),
                LaunchProfile.model_validate({"id": "cs", "label": "cs", "harness": "claude", "permissions": "skip_all"}),
                LaunchProfile.model_validate({"id": "ok", "label": "ok", "harness": "claude"})]
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: profiles)


@pytest.mark.parametrize("profile,tone,line", [
    ("cx", "danger", "plugin_agent_skips"),
    ("cl", "danger", "plugin_agent_custom"),
    ("cq", "danger", "plugin_agent_custom"),
    ("cs", "danger", "plugin_agent_skips"),
    ("bl", "danger", "plugin_agent_custom"),
    ("pa", "danger", "plugin_agent_custom"),
    ("ev", "confirm", "plugin_agent"),
    ("ok", "confirm", "plugin_agent"),
])
def test_real_launch_resolution_flags_custom_commands_and_skip_all(monkeypatch, profile, tone, line) -> None:
    _profiles(monkeypatch)
    project = {"id": 7, "name": "Flow", "path": "ssh://mac-b/work/flow", "default_launch_profile": profile}
    launch = launch_mod.resolve(project, None)
    assert launch.where == "paired computer mac-b"

    store = pending.PendingActions()
    monkeypatch.setattr(capabilities, "Projects", lambda: SimpleNamespace(get=lambda pid: dict(project)))
    port = SessionCreatePort(object(), store=store, wait_seconds=5.0, standing=lambda pid: "")

    async def run() -> Dict[str, Any]:
        task = asyncio.create_task(port.create("local/flow", 7, "hello there", None))
        await _parked(store)
        shown = store.list()[0]["display"]
        port.withdraw_for("local/flow")
        with pytest.raises(guards.Refused):
            await task
        return shown

    display = asyncio.run(run())
    assert display["tone"] == tone and display["consequences"][1]["key"] == line
    assert display["consequences"][0]["params"]["where"] == "paired computer mac-b"


def test_withdraw_denies_a_pending_item_only_while_it_is_pending() -> None:
    async def body() -> None:
        store = pending.PendingActions()

        async def noop() -> dict:
            raise AssertionError("withdraw must not run the action")

        def make(n: int) -> pending.PendingAction:
            return store.create(caller_session_id="c", caller_tmux="c", target_session_id="", target_tmux="", action="x",
                                args_summary="s", execute=noop if n == 0 else (lambda: _ok_result()), args={"n": n})

        pending_item, approved, denied = make(0), make(1), make(2)
        await store.approve(approved.id)
        store.deny(denied.id)
        assert store.withdraw(pending_item.id, "the plugin stopped") is True
        assert (pending_item.status, pending_item.reason) == (pending.DENIED, "the plugin stopped") and pending_item.result is None
        assert store.withdraw(approved.id, "late") is False and approved.status == pending.APPROVED and approved.reason == ""
        assert store.withdraw(denied.id, "late") is False and denied.reason == ""
        assert store.withdraw("act_unknown", "late") is False
        assert store.withdraw(pending_item.id, "again") is False and pending_item.reason == "the plugin stopped"

    async def _ok_result() -> dict:
        return {"content": [], "isError": False}

    asyncio.run(body())


def _byoai(monkeypatch: pytest.MonkeyPatch, connections: List[Any]) -> None:
    from src.config import settings

    monkeypatch.setattr(type(settings), "load_auth_config", lambda self: SimpleNamespace(byoai=SimpleNamespace(connections=connections)))


def test_a_byoai_connection_profile_resolves_with_the_real_connections(monkeypatch) -> None:
    from dataclasses import asdict

    from src.config import settings
    from src.config.launch_profiles import LaunchProfile
    from src.core.byoai.contracts import Connection

    profile = LaunchProfile.model_validate({"id": "or", "label": "or", "harness": "claude", "model": {"mode": "fixed", "value": "m-1"},
                                            "endpoint": {"mode": "connection", "connection_id": "c1"}})
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: [profile])
    project = {"id": 7, "name": "Flow", "path": "/work/flow", "default_launch_profile": "or"}
    _byoai(monkeypatch, [])
    with pytest.raises(launch_mod.LaunchUnresolvable):
        launch_mod.resolve(project, None)
    conn = Connection(id="c1", preset="openrouter", label="c1", base_url="https://openrouter.ai/api/v1", key_host="https://openrouter.ai", key_hint="cdef")
    _byoai(monkeypatch, [SimpleNamespace(model_dump=lambda: asdict(conn))])
    launch = launch_mod.resolve(project, None)
    assert (launch.profile_id, launch.permissions, launch.custom_command) == ("or", "harness_default", False)


def test_a_pinned_account_and_a_harness_that_needs_a_model_fail_closed(monkeypatch) -> None:
    from src.config import settings
    from src.config.launch_profiles import LaunchProfile
    from src.core.agent_families import AGENT_FAMILY_BY_NAME

    pinned = LaunchProfile.model_validate({"id": "pin", "label": "pin", "harness": "claude", "account": {"mode": "pinned", "account_id": "a1"}})
    needy = next(name for name, family in AGENT_FAMILY_BY_NAME.items() if family.needs_model)
    asks = LaunchProfile.model_validate({"id": "ask", "label": "ask", "harness": needy, "custom_command": {"script": 'run "$@"'}})
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: [pinned, asks])
    _byoai(monkeypatch, [])
    for pid in ("pin", "ask"):
        with pytest.raises(launch_mod.LaunchUnresolvable):
            launch_mod.resolve({"id": 7, "name": "Flow", "path": "/work/flow", "default_launch_profile": pid}, None)
