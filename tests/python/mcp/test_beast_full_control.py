
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.mcp import beast_mode, pending, session_target, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from src.cplugs.host import mcp as cplug_mcp  # noqa: E402
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PANE = AgentCaller("ses_cloude_a", "cloude_a", "ses_cloude_a")
ASLEEP = "aaaaaaaa-1111-4111-8111-111111111111"
FINGERPRINT = "f" * 64
SEEN: dict = {}


GRID: dict = {}
PERMISSION_OPTIONS = ["Yes", "Yes, and don't ask again for touch commands in /w", "No, and tell Claude what to do differently"]


def _dialog(startup_kind=None, fingerprint: str = FINGERPRINT, kind: str = "permission", options=None,
            multi_select: bool = False, tabs=None) -> dict:
    return {"kind": kind if startup_kind is None else "folder_trust", "fingerprint": fingerprint,
            "startup_kind": startup_kind, "options": list(PERMISSION_OPTIONS if options is None else options),
            "multi_select": multi_select, "tabs": tabs or []}


def _info(name: str) -> SimpleNamespace:
    return SimpleNamespace(activity_status="idle", status_source="none", subagents_running=None, background_open=None,
                           tmux_session=name, host_key="local", session_row_id=9, label=None, host_label="here",
                           session=SimpleNamespace(id=f"ses_{name}", working_dir="/w", tmux_created_epoch=1))


class View:
    gate_waited = False

    def __init__(self):
        self.app = SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(registry=SimpleNamespace(subscribers={}))))

    async def list_session_infos(self):
        return [_info("cloude_a"), _info("cloude_b")]

    async def list_peer_infos(self):
        return []

    def fresh(self):
        return self


@pytest.fixture()
def world(monkeypatch):
    from src.api import projects_routes, session_dialog_routes, session_sleep_routes
    from src.core.crosstalk import directory
    from src.models.dialogs import DialogAnswerResponse, DialogResponse

    calls: list = []
    armed = {"on": False}
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    GRID.clear()
    arm_beast(monkeypatch, lambda: armed["on"], GRID)
    monkeypatch.setattr(directory, "_asleep_rows", lambda: [{"id": 5, "session_uuid": ASLEEP, "tmux_name": "cloude_nap"}])
    SEEN.clear()
    SEEN.update({"ses_cloude_a": _dialog(), "ses_cloude_b": _dialog()})

    async def wake(request, session_uuid, body=None):
        calls.append(("wake", session_uuid))
        return {"status": "recreated"}

    async def create(body):
        calls.append(("create_project", body.name))
        return {"id": 1, "name": body.name}

    async def answer(request, session_id, body):
        calls.append(("answer", session_id))
        return DialogAnswerResponse(kind="permission", fingerprint=body.fingerprint)

    monkeypatch.setattr(session_sleep_routes, "wake_session", wake)
    monkeypatch.setattr(projects_routes, "create_project", create)
    async def get_dialog(request, session_id):
        return DialogResponse(dialog=SEEN.get(session_id))

    monkeypatch.setattr(session_dialog_routes, "answer_session_dialog", answer)
    monkeypatch.setattr(session_dialog_routes, "get_dialog", get_dialog)
    return calls, armed


WRITES = [
    ("session_wake", {"target": ASLEEP}, ("wake", ASLEEP)),
    ("project_create", {"name": "demo", "path": "/tmp/demo"}, ("create_project", "demo")),
    ("session_dialog_answer", {"target": "cloude_b", "fingerprint": FINGERPRINT, "choice": {"option": "Yes"}},
     ("answer", "ses_cloude_b")),
]


def _call(name, args, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(View(), caller, name, args))


@pytest.mark.parametrize("name,args,expected", WRITES, ids=[w[0] for w in WRITES])
def test_with_beast_off_a_new_write_waits(world, name, args, expected):
    calls, _ = world
    assert "pending" in str(_call(name, args)) and calls == []
    assert [i["action"] for i in pending.get_store().list()] == [name]


@pytest.mark.parametrize("name,args,expected", WRITES, ids=[w[0] for w in WRITES])
def test_with_beast_on_a_new_write_runs_at_once_and_is_recorded(world, name, args, expected):
    calls, armed = world
    armed["on"] = True
    answer = _call(name, args)
    assert not answer.get("isError") and "pending" not in str(answer), answer
    assert calls == [expected] and pending.get_store().list() == []
    assert [d["action"] for d in pending.get_store().decided()] == [name]


def test_arming_beast_approves_a_new_write_already_waiting(world):
    calls, armed = world
    _call("session_wake", {"target": ASLEEP})
    armed["on"] = True
    assert asyncio.run(beast_mode.approve_pending()) == 1 and calls == [("wake", ASLEEP)]


def test_your_own_dialog_still_waits_with_beast_on(world):
    calls, armed = world
    armed["on"] = True
    held = _call("session_dialog_answer", {"target": "cloude_a", "fingerprint": FINGERPRINT, "choice": {"option": "Yes"}})
    assert "pending" in str(held) and calls == []
    assert asyncio.run(beast_mode.approve_pending()) == 0, "arming never approves an agent's own dialog"


@pytest.mark.parametrize("seen", [_dialog(startup_kind="trust"), _dialog(startup_kind="other"), None,
                                  _dialog(fingerprint="e" * 64)],
                         ids=["trust_screen", "other_startup_screen", "none_open", "a_different_dialog"])
def test_a_startup_screen_or_an_unread_dialog_waits_for_the_owner_with_beast_on(world, seen):
    calls, armed = world
    armed["on"] = True
    SEEN["ses_cloude_b"] = seen
    held = _call("session_dialog_answer", {"target": "cloude_b", "fingerprint": FINGERPRINT, "choice": {"option": "Yes"}})
    assert "pending" in str(held) and calls == []
    assert asyncio.run(beast_mode.approve_pending()) == 0, "arming never approves a held startup answer"
    assert [i["action"] for i in pending.get_store().list()] == ["session_dialog_answer"]


def test_always_waits_still_waits_with_beast_on(world, monkeypatch):
    calls, armed = world
    armed["on"] = True
    for name in beast_mode.ALWAYS_WAITS:
        assert beast_mode.eligible_action(name) is False and beast_mode.approval_skip(name) is False, name

    async def name_of(project_id, include_archived=False):
        return "demo"

    from src.core.mcp import project_tools

    monkeypatch.setattr(project_tools, "_current_name", name_of)
    assert "pending" in str(_call("project_delete", {"project": 3}))
    assert "pending" in str(_call("session_delete", {"target": "cloude_b"}))
    assert "pending" in str(_call("dashboard_delete", {"dashboard_id": "b2"}))
    assert {i["action"] for i in pending.get_store().list()} == {"project_delete", "session_delete", "dashboard_delete"}


def test_beast_covers_every_write_tool_but_the_always_wait_set_and_plugin_inbox_tools():
    for name in tools.WRITE_TOOLS:
        expected = name not in beast_mode.ALWAYS_WAITS and name not in cplug_mcp.INBOX_TOOLS
        assert beast_mode.eligible_action(name) is expected, name
    assert beast_mode.eligible_action("crosstalk_resume") is False


def test_always_waits_is_declared_once():
    hits = [p for p in (ROOT / "src").rglob("*.py") if "ALWAYS_WAITS = " in p.read_text()]
    assert [p.relative_to(ROOT).as_posix() for p in hits] == ["src/core/mcp/beast_mode.py"]


def test_no_tool_can_turn_beast_mode_on(world, monkeypatch):
    from src.api import beast_mode_routes
    from src.core.mcp import beast_tools
    from src.cplugs.host import runtime
    from src.cplugs.sdk import beast_mode as door

    sent: list = []

    async def put(body, source):
        sent.append(body.enabled)
        return {"enabled": body.enabled}

    monkeypatch.setattr(beast_mode_routes, "set_beast_mode", put)
    assert _call("beastmode_off", {"enabled": True})["isError"] is True and sent == []
    assert not _call("beastmode_off", {}).get("isError") and sent == [False]
    for row in tools.tool_definitions(None):
        if "beast" in row["name"]:
            assert row["inputSchema"]["properties"] == {}, row["name"]
    switch = ("put_beast_mode", "_persist_beast_mode", "beast_store", "BeastSetting(")
    handlers = [handler for (_d, _p, _r, handler) in tools._TOOLS.values()]
    handlers += [spec.handler for d in runtime.definitions() for spec in d.tools.values()]
    for handler in handlers:
        source = Path(inspect.getsourcefile(handler)).read_text()
        reached = [s for s in switch if s in source]
        if handler is beast_tools.beastmode_off:
            assert "BeastSetting(enabled=False)" in source and "enabled=True" not in source and "beast_store" not in source
            continue
        assert reached == [], (handler, reached)
    door_source = Path(inspect.getsourcefile(door)).read_text()
    assert "BeastSetting(enabled=False)" in door_source and "enabled=True" not in door_source
    assert not [n for n in dir(door) if n.startswith("arm") and n != "armed"], "the SDK door must offer no arm call"


def test_beast_mode_off_runs_at_once_for_an_external_token(world, monkeypatch):
    from src.api import beast_mode_routes

    sources = []

    async def put(body, source):
        sources.append(source)
        return {"enabled": False}

    monkeypatch.setattr(beast_mode_routes, "set_beast_mode", put)
    external = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="laptop")
    answer = _call("beastmode_off", {}, external)
    assert not answer.get("isError") and "pending" not in str(answer)
    assert sources == ["mcp:mcp-token:1"], "the off names its caller in the log source"


def test_resolver_is_unaffected_by_beast(world):
    _, armed = world
    for on in (False, True):
        armed["on"] = on
        answer = _call("session_send_keys", {"target": ASLEEP, "text": "hi"})
        assert answer["isError"] is True and "session_wake" in answer["content"][0]["text"]
    assert session_target.LIVE == "live"


LOCKED_ANSWERS = [
    (_dialog(kind="ask_user_question", options=["Blue", "Red"]), {"option": "Blue"}),
    (_dialog(), {"other": "do it differently"}),
    (_dialog(kind="plan_approval", options=["Yes, and auto-accept edits", "Yes, and manually approve edits", "No"]),
     {"option": "Yes, and auto-accept edits"}),
    (_dialog(), {"option": PERMISSION_OPTIONS[1]}),
    (_dialog(options=["Yes, and don't ask again", "No"]), {"plain": "yes"}),
    (_dialog(kind="other", options=["Yes, allow external imports", "No"]), {"option": "Yes, allow external imports"}),
    (_dialog(kind="unreadable", options=[]), {"option": "Yes"}),
    (_dialog(multi_select=True, options=["Yes", "No"]), {"option": "Yes"}),
]
LOCKED_IDS = ["question", "free_text", "plan_approval", "dont_ask_again", "only_yes_widens", "other_screen", "unreadable",
              "multi_select"]


@pytest.mark.parametrize("seen,choice", LOCKED_ANSWERS, ids=LOCKED_IDS)
@pytest.mark.parametrize("mode", ["armed_beast_on_box", "disarmed_beast_off_box"])
def test_a_locked_dialog_answer_waits_for_the_owner_whatever_the_agent_writes_row_says(world, seen, choice, mode):
    calls, armed = world
    armed["on"] = mode.startswith("armed")
    GRID.update({"agentWritesOff": True, "agentWritesOn": True})
    assert beast_mode.approval_skip("session_dialog_answer") is True
    SEEN["ses_cloude_b"] = seen
    held = _call("session_dialog_answer", {"target": "cloude_b", "fingerprint": FINGERPRINT, "choice": choice})
    assert "pending" in str(held) and calls == []
    if armed["on"]:
        assert asyncio.run(beast_mode.approve_pending()) == 0, "arming never approves a locked answer"
    assert [i["action"] for i in pending.get_store().list()] == ["session_dialog_answer"]


@pytest.mark.parametrize("choice", [{"option": "Yes"}, {"plain": "yes"}, {"plain": "no"}, {"option": PERMISSION_OPTIONS[2]}],
                         ids=["option_yes", "plain_yes", "plain_no", "option_no"])
def test_a_plain_yes_or_no_on_a_permission_stays_covered_with_beast_off_ticked(world, choice):
    calls, _ = world
    GRID.update({"agentWritesOff": True})
    answer = _call("session_dialog_answer", {"target": "cloude_b", "fingerprint": FINGERPRINT, "choice": choice})
    assert "pending" not in str(answer) and calls == [("answer", "ses_cloude_b")], answer


def test_a_questions_answer_always_waits_even_with_every_box_ticked(world):
    calls, armed = world
    armed["on"] = True
    GRID.update({"agentWritesOff": True, "agentWritesOn": True})
    SEEN["ses_cloude_b"] = {**_dialog(kind="ask_user_question", options=["Blue"]), "questions_fingerprint": FINGERPRINT}
    held = _call("session_dialog_questions_answer", {"target": "cloude_b", "questions_fingerprint": FINGERPRINT,
                                                     "answers": [{"option": "Blue"}]})
    assert "pending" in str(held) and calls == [] and asyncio.run(beast_mode.approve_pending()) == 0


def test_the_real_switch_path_arms_full_control_without_patching_beast_enabled(monkeypatch):
    from src.api import session_sleep_routes
    from src.config import settings
    from src.core.crosstalk import directory

    switch = SimpleNamespace(beast_mode=False, beast_prompts=False, beast_mode_until=None, beast_grid={}, beast_trust_scope="projects")
    monkeypatch.setattr(type(settings), "load_auth_config", lambda self: SimpleNamespace(mcp=switch))
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(directory, "_asleep_rows", lambda: [{"id": 5, "session_uuid": ASLEEP, "tmux_name": "cloude_nap"}])
    calls: list = []

    async def wake(request, session_uuid, body=None):
        calls.append(session_uuid)
        return {"status": "recreated"}

    monkeypatch.setattr(session_sleep_routes, "wake_session", wake)
    assert not beast_mode.beast_enabled()
    assert "pending" in str(_call("session_wake", {"target": ASLEEP})) and calls == []
    switch.beast_mode = True
    assert beast_mode.beast_enabled() is True
    assert "pending" not in str(_call("session_wake", {"target": ASLEEP})) and calls == [ASLEEP]
    switch.beast_mode_until = "2020-01-01T00:00:00+00:00"
    assert beast_mode.beast_enabled() is False and "pending" in str(_call("session_wake", {"target": ASLEEP}))
