
from __future__ import annotations

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import RigSlot, binary_missing, claude_script, seed_claude_config
from tests.rig.test_dialog_answer import ASK, call, tool_results, wait_for


def test_open_for_a_session_answer_closes_then_gone(rig_slot: RigSlot, tmp_path) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    with ScriptedModel([Step("RIG:ask", "AskUserQuestion", ASK)]) as model, sync_playwright() as pw:
        cdir, cwork = tmp_path / "ccfg", tmp_path / "cw"
        cwork.mkdir()
        seed_claude_config(cdir, cwork)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        browser = pw.chromium.launch()
        ctx = browser.new_context(storage_state=rig_slot.slot.auth, viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(rig_slot.slot.base + "/")
        name = rig_slot.create_session("rigapp", "rigclaude", cwork)
        rig_slot.wait_for(name, "❯")
        rig_slot.type_line(name, "RIG:ask please")
        rig_slot.wait_for(name, "Pick a colour?")
        wait_for(lambda: call(rig_slot, "GET", "/api/v1/approvals")[1]["items"], "server never listed the dialog", timeout=30)
        sid = call(rig_slot, "GET", "/api/v1/approvals")[1]["items"][0]["session_id"]
        url_before = page.url
        page.wait_for_function("() => !!(window.CloudeWeb && window.CloudeWeb.openApprovalFor)")

        assert page.evaluate("id => window.CloudeWeb.openApprovalFor(id)", sid) == "opened"
        inbox = page.locator("[data-approval-inbox]")
        card = inbox.locator("[data-approval-card]")
        expect(card).to_have_count(1)
        expect(card).to_contain_text("Pick a colour?")
        assert page.url == url_before, "a question click must never navigate"
        with pytest.raises(AssertionError):
            expect(inbox).to_have_count(0, timeout=500)

        card.get_by_role("button", name="Blue").click()
        wait_for(lambda: "Blue" in tool_results(model), "claude never got the answer", timeout=30)
        expect(inbox).to_have_count(0, timeout=20000)
        expect(page.locator("[data-approval-empty]")).to_have_count(0)

        assert page.evaluate("id => window.CloudeWeb.openApprovalFor(id)", sid) == "gone"
        expect(inbox).to_have_count(0)
        expect(page.locator(".toast", has_text="already answered")).to_be_visible(timeout=5000)
        browser.close()
