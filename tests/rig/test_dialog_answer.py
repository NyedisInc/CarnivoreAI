
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple

import pytest

from src.core.approvals.extract import extract_dialog
from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import (
    RigSlot, binary_missing, claude_script, codex_script, seed_claude_config, seed_codex_home)

ASK = {"questions": [{"question": "Pick a colour?", "header": "Colour", "multiSelect": False,
                      "options": [{"label": "Red", "description": "warm"},
                                  {"label": "Blue", "description": "cool"}]}]}
MULTI = {"questions": [{"question": "Which toppings?", "header": "Top", "multiSelect": True,
                        "options": [{"label": "Cheese", "description": "a"}, {"label": "Ham", "description": "b"},
                                    {"label": "Olives", "description": "c"}]}]}
RUN = {"cmd": "touch rigfile", "sandbox_permissions": "require_escalated", "justification": "rig wants a file"}


def call(slot, method: str, path: str, body: Any = None) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(
        slot.slot.base + path, method=method, data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + slot.slot.token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"null")


def session_id(slot, tmux_name: str) -> str:
    rows = slot.slot.api("GET", "/api/v1/sessions/list")
    return next(r["session"]["id"] for r in rows if r["tmux_session"] == tmux_name)


def wait_dialog(slot, sid: str, timeout: float = 30.0) -> Dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _, got = call(slot, "GET", f"/api/v1/sessions/{sid}/dialog")
        if got and got["dialog"]:
            return got["dialog"]
        time.sleep(1.0)
    raise AssertionError("the watcher never published a dialog")


def tool_results(model) -> str:
    out = []
    for req in model.requests_to("/v1/messages"):
        for msg in req.get("messages", []):
            content = msg.get("content")
            out += [json.dumps(b.get("content")) for b in (content if isinstance(content, list) else [])
                    if b.get("type") == "tool_result"]
    return "\n".join(out)


def wait_for(cond, what: str, timeout: float = 45.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(1.0)
    raise AssertionError(what)


def test_answer_real_claude_and_real_codex(rig_slot: RigSlot, tmp_path) -> None:
    for name in ("claude", "codex"):
        if binary_missing(name):
            pytest.skip(binary_missing(name))
    with ScriptedModel([Step("RIG:ask", "AskUserQuestion", ASK), Step("RIG:multi", "AskUserQuestion", MULTI), Step("RIG:run", "exec_command", RUN)]) as model:
        cdir, xhome, cwork, xwork = (tmp_path / n for n in ("ccfg", "xhome", "cw", "xw"))
        cwork.mkdir(), xwork.mkdir()
        seed_claude_config(cdir, cwork)
        seed_codex_home(xhome, model.url, xwork)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        rig_slot.register_wrapper("rigcodex", "codex", codex_script(xhome))

        cl = rig_slot.create_session("rigc", "rigclaude", cwork)
        sid = session_id(rig_slot, cl)
        rig_slot.wait_for(cl, "❯")
        rig_slot.type_line(cl, "RIG:ask please")
        rig_slot.wait_for(cl, "Pick a colour?")
        dialog = wait_dialog(rig_slot, sid)
        assert dialog["question"] == "Pick a colour?" and dialog["options"] == ["Red", "Blue"]
        path = f"/api/v1/sessions/{sid}/dialog/answer"

        before = rig_slot.capture(cl)
        status, body = call(rig_slot, "POST", path, {"fingerprint": "0" * 64, "choice": {"option": "Blue"}})
        assert (status, body["detail"]["reason"]) == (409, "dialog_changed")
        time.sleep(1.0)
        assert rig_slot.capture(cl) == before
        assert extract_dialog(before, "claude").fingerprint == dialog["fingerprint"]

        status, body = call(rig_slot, "POST", path,
                            {"fingerprint": dialog["fingerprint"], "choice": {"option": "Blue"}})
        assert status == 200 and body["kind"] == "ask_user_question"

        wait_for(lambda: "Blue" in tool_results(model), "the scripted model never saw a tool_result carrying Blue")
        status, _ = call(rig_slot, "POST", path, {"fingerprint": dialog["fingerprint"], "choice": {"dismiss": True}})
        assert status == 409

        cm = rig_slot.create_session("rigm", "rigclaude", cwork)
        sid = session_id(rig_slot, cm)
        path = f"/api/v1/sessions/{sid}/dialog/answer"
        rig_slot.wait_for(cm, "❯")
        rig_slot.type_line(cm, "RIG:multi please")
        rig_slot.wait_for(cm, "Which toppings?")
        dialog = wait_dialog(rig_slot, sid)
        assert dialog["multi_select"] and dialog["options"] == ["Cheese", "Ham", "Olives"]
        status, body = call(rig_slot, "POST", path, {"fingerprint": dialog["fingerprint"],
                                                     "choice": {"options": ["Cheese", "Olives"]}})
        assert status == 200, (body, rig_slot.capture(cm))
        wait_for(lambda: "Olives" in tool_results(model), "the multi-select answer never came back " + rig_slot.capture(cm), 15)
        assert "Ham" not in tool_results(model).split("Blue")[-1]

        cx = rig_slot.create_session("rigx", "rigcodex", xwork)
        xid = session_id(rig_slot, cx)
        rig_slot.wait_for(cx, "Ask Codex to do anything")
        rig_slot.type_line(cx, "RIG:run please")
        rig_slot.wait_for(cx, "Would you like to run the following command?")
        dialog = wait_dialog(rig_slot, xid)
        assert dialog["kind"] == "codex_approval" and dialog["options"][0] == "Yes, proceed"
        status, _ = call(rig_slot, "POST", f"/api/v1/sessions/{xid}/dialog/answer",
                         {"fingerprint": dialog["fingerprint"], "choice": {"option": "Yes, proceed"}})
        assert status == 200
        wait_for((xwork / "rigfile").exists, "codex never ran the approved command")
