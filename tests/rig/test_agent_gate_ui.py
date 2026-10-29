
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
from playwright.sync_api import Page, expect, sync_playwright

from src.core.product_identity import strip_session_prefix
from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import RigSlot, binary_missing, claude_script, seed_claude_config
from tests.rig.test_dialog_answer import call, session_id, wait_for

TOOL = "mcp__carnivore__session_stop"
CARD = '#approvals-panel [data-approval-card][data-source="agent_action"]'
GATE = "[data-agent-gate='switch']"


def tool_result_blocks(model: ScriptedModel) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for req in model.requests_to("/v1/messages"):
        for msg in req.get("messages", []):
            content = msg.get("content")
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_result":
                    out.append({"error": bool(block.get("is_error")), "text": json.dumps(block.get("content"))})
    return out


def is_asleep(slot: RigSlot, tmux_name: str) -> bool:
    return tmux_name in json.dumps(call(slot, "GET", "/api/v1/sessions/asleep")[1])


def caller_asks(slot: RigSlot, model: ScriptedModel, cwork: Path, tag: str, target_id: str) -> str:
    model.steps.append(Step(f"RIG:{tag}", TOOL, {"target": target_id}))
    a = slot.create_session(f"riga{tag}", "rigclaude", cwork)
    slot.wait_for(a, "❯")
    slot.type_line(a, f"RIG:{tag} please")
    slot.wait_for(a, "Do you want to proceed?")
    slot._tmux("send-keys", "-t", f"={a}:", "Enter")
    return a


def set_gate(slot: RigSlot, on: bool) -> None:
    call(slot, "PUT", "/api/v1/agent-actions/settings", {"gate_cross_session_actions": on})


def shot(page: Page, name: str) -> None:
    if os.environ.get("A5_SHOTS"):
        Path(os.environ["A5_SHOTS"]).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(os.environ["A5_SHOTS"]) / f"{name}.png"))


def test_agent_action_card_approve_deny_and_gate_toggle(rig_slot: RigSlot, tmp_path) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    with ScriptedModel([]) as model, sync_playwright() as pw:
        cdir, cwork = rig_slot.slot.dir / "home" / ".claude", tmp_path / "cw"
        cwork.mkdir()
        seed_claude_config(cdir, cwork)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        set_gate(rig_slot, True)
        assert call(rig_slot, "GET", "/api/v1/agent-actions/settings")[1] == {"gate_cross_session_actions": True}
        targets = {}
        for tag in ("approve", "deny", "off"):
            name = rig_slot.create_session(f"rigb{tag}", "rigclaude", cwork)
            rig_slot.wait_for(name, "❯")
            rig_slot.type_line(name, "hello there")
            rig_slot.wait_for(name, "rig: ok", 45)
            targets[tag] = (name, session_id(rig_slot, name))
        browser = pw.chromium.launch()
        ctx = browser.new_context(storage_state=rig_slot.slot.auth, viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(rig_slot.slot.base + "/")
        try:
            def open_ask(target: str) -> None:
                page.wait_for_function("() => !!(window.CloudeWeb && window.CloudeWeb.openApprovalFor)")
                wait_for(lambda: page.evaluate("id => window.CloudeWeb.openApprovalFor(id)", target) == "opened",
                         "the question modal never opened", 30)

            b_name, b_id = targets["approve"]
            a = caller_asks(rig_slot, model, cwork, "approve", b_id)
            open_ask(b_id)
            card = page.locator(CARD)
            expect(card).to_have_count(1, timeout=30000)
            for text in (strip_session_prefix(a), strip_session_prefix(b_name), "stop"):
                expect(card).to_contain_text(text)
            shot(page, "a5-card-desktop-1440")
            with page.expect_response(lambda r: r.url.endswith("/approve")) as approve:
                page.locator("#approvals-panel [data-approval-approve-action]").click()
            assert approve.value.status == 200, approve.value.text()
            assert approve.value.json().get("status") == "approved", approve.value.text()
            assert "asleep" in json.dumps(approve.value.json().get("result")), approve.value.text()
            wait_for(lambda: is_asleep(rig_slot, b_name), f"{b_name} never went to sleep", 30)
            wait_for(lambda: any(not b["error"] and "asleep" in b["text"] for b in tool_result_blocks(model)), f"A never saw success: {tool_result_blocks(model)}", 30)
            expect(page.locator(CARD)).to_have_count(0, timeout=20000)
            approved_results = len(tool_result_blocks(model))

            b_name, b_id = targets["deny"]
            a = caller_asks(rig_slot, model, cwork, "deny", b_id)
            if not page.locator("#approvals-panel").is_visible():
                open_ask(b_id)
            expect(page.locator(CARD)).to_have_count(1, timeout=30000)
            shot(page, "a5-card-before-deny")
            page.locator("#approvals-panel [data-approval-deny-action]").click()
            wait_for(lambda: any(b["error"] for b in tool_result_blocks(model)[approved_results:]),
                     f"A never got a tool error: {tool_result_blocks(model)}", 30)
            expect(page.locator(CARD)).to_have_count(0, timeout=20000)
            assert not is_asleep(rig_slot, b_name)
            assert "❯" in rig_slot.capture(b_name)

            page.goto(rig_slot.slot.base + "/#settings/sessions/agents")
            switch = page.locator(GATE)
            expect(switch).to_be_visible(timeout=30000)
            expect(page.locator("[data-agent-gate='panel'] [role='alert']")).to_have_count(0)
            shot(page, "a5-settings-gate-on")
            with page.expect_response(lambda r: r.url.endswith("/agent-actions/settings") and r.request.method == "PUT") as put:
                switch.click()
            assert put.value.status == 200 and json.loads(put.value.request.post_data) == {"gate_cross_session_actions": False}
            assert put.value.json() == {"gate_cross_session_actions": False}
            assert call(rig_slot, "GET", "/api/v1/agent-actions/settings")[1] == {"gate_cross_session_actions": False}
            shot(page, "a5-settings-gate-off")

            b_name, b_id = targets["off"]
            seen = len(tool_result_blocks(model))
            caller_asks(rig_slot, model, cwork, "off", b_id)
            wait_for(lambda: is_asleep(rig_slot, b_name), f"{b_name} did not sleep with the gate off", 40)
            assert any(not b["error"] for b in tool_result_blocks(model)[seen:])
            assert [i for i in call(rig_slot, "GET", "/api/v1/approvals")[1]["items"] if i["source"] == "agent_action"] == []

            with page.expect_response(lambda r: r.url.endswith("/agent-actions/settings") and r.request.method == "PUT") as back:
                switch.click()
            assert back.value.json() == {"gate_cross_session_actions": True}
            assert call(rig_slot, "GET", "/api/v1/agent-actions/settings")[1] == {"gate_cross_session_actions": True}
        finally:
            set_gate(rig_slot, False)
            browser.close()
