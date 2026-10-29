
from __future__ import annotations

import pytest

from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import (
    RigSlot, binary_missing, claude_script, codex_script, seed_claude_config, seed_codex_home)
from tests.rig.test_dialog_answer import RUN, call, session_id, tool_results, wait_dialog, wait_for

WIDTH = 40
LONG_ASK = {"questions": [{"question": "Which deployment environment should the release candidate be promoted to first this week?",
                           "header": "Env", "multiSelect": False,
                           "options": [{"label": "Staging cluster in the east region", "description": "Safest, mirrors production traffic patterns closely"},
                                       {"label": "Production canary at five percent", "description": "Fastest feedback but touches real customers right away"}]}]}


def narrow(slot: RigSlot, tmux_name: str) -> None:
    slot._tmux("resize-window", "-t", f"={tmux_name}:", "-x", str(WIDTH), "-y", "45")


def test_wrapped_dialogs_are_listed_and_answered_at_40_columns(rig_slot: RigSlot, tmp_path) -> None:
    for name in ("claude", "codex"):
        if binary_missing(name):
            pytest.skip(binary_missing(name))
    with ScriptedModel([Step("RIG:long", "AskUserQuestion", LONG_ASK), Step("RIG:run", "exec_command", RUN)]) as model:
        cdir, xhome, cwork, xwork = (tmp_path / n for n in ("ccfg", "xhome", "cw", "xw"))
        cwork.mkdir(), xwork.mkdir()
        seed_claude_config(cdir, cwork)
        seed_codex_home(xhome, model.url, xwork)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        rig_slot.register_wrapper("rigcodex", "codex", codex_script(xhome))

        cl = rig_slot.create_session("rign", "rigclaude", cwork)
        sid = session_id(rig_slot, cl)
        rig_slot.wait_for(cl, "❯")
        narrow(rig_slot, cl)
        rig_slot.type_line(cl, "RIG:long please")
        rig_slot.wait_for(cl, "Esc", 40)
        dialog = wait_dialog(rig_slot, sid)
        assert dialog["options"] == ["Staging cluster in the east region", "Production canary at five percent"]
        assert any(i["session_id"] == sid for i in call(rig_slot, "GET", "/api/v1/approvals")[1]["items"])
        status, body = call(rig_slot, "POST", f"/api/v1/sessions/{sid}/dialog/answer",
                            {"fingerprint": dialog["fingerprint"], "choice": {"option": "Production canary at five percent"}})
        assert status == 200, (body, rig_slot.capture(cl))
        wait_for(lambda: "Production canary" in tool_results(model), "claude never got the answer " + rig_slot.capture(cl), 30)
        rig_slot.wait_for(cl, "❯", 30)

        cx = rig_slot.create_session("rigx", "rigcodex", xwork)
        xid = session_id(rig_slot, cx)
        rig_slot.wait_for(cx, "Ask Codex to do anything")
        narrow(rig_slot, cx)
        rig_slot.type_line(cx, "RIG:run please")
        rig_slot.wait_for(cx, "Would you like to run", 40)
        dialog = wait_dialog(rig_slot, xid)
        assert dialog["kind"] == "codex_approval" and dialog["options"][0] == "Yes, proceed"
        status, body = call(rig_slot, "POST", f"/api/v1/sessions/{xid}/dialog/answer",
                            {"fingerprint": dialog["fingerprint"], "choice": {"option": "Yes, proceed"}})
        assert status == 200, (body, rig_slot.capture(cx))
        wait_for(lambda: (xwork / "rigfile").exists(), "codex never ran the approved command " + rig_slot.capture(cx), 30)
