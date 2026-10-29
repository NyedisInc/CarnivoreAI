
from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import RigSlot, binary_missing, claude_script, seed_claude_config
from tests.rig.test_dialog_answer import ASK, call, session_id, tool_results, wait_for


def set_theme(slot: RigSlot, theme: str) -> None:
    _, cur = call(slot, "GET", "/api/v1/preferences")
    status, _ = call(slot, "PATCH", "/api/v1/preferences",
                     {"changes": {"theme": theme}, "expected_revision": cur.get("revision")})
    assert status == 200


@pytest.mark.parametrize("theme,width,height", [
    ("carnivore", 1440, 900), ("green_crt", 1440, 900), ("carnivore", 390, 844), ("green_crt", 390, 844)])
def test_inbox_badge_card_answer_clear(rig_slot: RigSlot, tmp_path, theme: str, width: int, height: int) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    set_theme(rig_slot, theme)
    shots = Path(os.environ["A4_SHOTS"]) if os.environ.get("A4_SHOTS") else None
    with ScriptedModel([Step("RIG:ask", "AskUserQuestion", ASK)]) as model, sync_playwright() as pw:
        cdir, cwork = tmp_path / "ccfg", tmp_path / "cw"
        cwork.mkdir()
        seed_claude_config(cdir, cwork)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        browser = pw.chromium.launch()
        ctx = browser.new_context(storage_state=rig_slot.slot.auth, viewport={"width": width, "height": height})
        page = ctx.new_page()
        page.goto(rig_slot.slot.base + "/")
        expect(page.locator("#session-sidebar-panel, .oc-topbar").first).to_be_attached(timeout=30000)
        page.wait_for_timeout(2000)
        assert call(rig_slot, "GET", "/api/v1/approvals")[1]["items"] == []
        expect(page.locator("[data-inbox-door], #approvalsBtn")).to_have_count(0)
        name = rig_slot.create_session("rigapp", "rigclaude", cwork)
        rig_slot.wait_for(name, "❯")
        rig_slot.type_line(name, "RIG:ask please")
        rig_slot.wait_for(name, "Pick a colour?")
        wait_for(lambda: call(rig_slot, "GET", "/api/v1/approvals")[1]["items"], "server never listed the dialog", timeout=30)
        page.wait_for_function("() => !!(window.CloudeWeb && window.CloudeWeb.openApprovalFor)")
        sid = session_id(rig_slot, name)
        wait_for(lambda: page.evaluate("id => window.CloudeWeb.openApprovalFor(id)", sid) == "opened", "modal never opened", 30)
        inbox = page.locator("[data-approval-inbox]")
        card = inbox.locator("[data-approval-card]")
        expect(card).to_have_count(1)
        expect(card).to_contain_text("Pick a colour?")
        expect(card.get_by_role("button", name="Blue")).to_be_visible()
        if width < 1024:
            box = inbox.bounding_box()
            assert box and box["width"] >= width - 4
        if shots:
            shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots / f"inbox-{theme}-{width}.png"))
        card.get_by_role("button", name="Blue").click()
        page.wait_for_timeout(4000)
        said = inbox.locator("[data-approval-notice]").all_inner_texts()
        wait_for(lambda: "Blue" in tool_results(model), f"claude never got the answer; inbox said {said}", timeout=30)
        expect(inbox).to_have_count(0, timeout=20000)
        assert call(rig_slot, "GET", "/api/v1/approvals")[1]["items"] == []
        if shots:
            page.screenshot(path=str(shots / f"inbox-{theme}-{width}-cleared.png"))
        browser.close()
