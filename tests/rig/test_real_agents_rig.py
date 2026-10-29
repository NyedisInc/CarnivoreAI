
from __future__ import annotations

import sys

import pytest

from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.anthropic_sse import RIG_MODEL
from tests.helpers.scripted_model.rig import (
    RigSlot, binary_missing, claude_script, codex_script, keychain_service_names,
    seed_claude_config, seed_codex_home)

ASK = {"questions": [{"question": "Pick a colour?", "header": "Colour", "multiSelect": False,
                      "options": [{"label": "Red", "description": "warm"},
                                  {"label": "Blue", "description": "cool"}]}]}
RUN = {"cmd": "touch rigfile", "sandbox_permissions": "require_escalated", "justification": "rig wants a file"}


def test_real_claude_ask_and_real_codex_approval(rig_slot: RigSlot, tmp_path) -> None:
    if sys.platform != "darwin":
        pytest.skip("the Keychain assertion needs macOS")
    for name in ("claude", "codex"):
        if binary_missing(name):
            pytest.skip(binary_missing(name))
    keychain_before = keychain_service_names()
    steps = [Step("RIG:ask", "AskUserQuestion", ASK), Step("RIG:run", "exec_command", RUN)]
    with ScriptedModel(steps) as model:
        claude_dir, codex_home = tmp_path / "claude-cfg", tmp_path / "codex-home"
        claude_work, codex_work = tmp_path / "cwork", tmp_path / "xwork"
        for d in (claude_work, codex_work):
            d.mkdir()
        seed_claude_config(claude_dir, claude_work)
        seed_codex_home(codex_home, model.url, codex_work)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, claude_dir))
        rig_slot.register_wrapper("rigcodex", "codex", codex_script(codex_home))

        cl = rig_slot.create_session("rigc", "rigclaude", claude_work)
        rig_slot.wait_for(cl, "❯")
        rig_slot.type_line(cl, "RIG:ask please")
        pane = rig_slot.wait_for(cl, "Pick a colour?")
        assert "Red" in pane and "Blue" in pane

        cx = rig_slot.create_session("rigx", "rigcodex", codex_work)
        rig_slot.wait_for(cx, "Ask Codex to do anything")
        rig_slot.type_line(cx, "RIG:run please")
        pane = rig_slot.wait_for(cx, "Would you like to run the following command?")
        assert "touch rigfile" in pane

        assert any(r.get("model") == RIG_MODEL for r in model.requests_to("/v1/messages"))
        assert model.requests_to("/v1/responses")
    assert keychain_service_names() == keychain_before
