
from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import RigSlot, binary_missing, claude_script, open_questions, seed_claude_config
from tests.rig.test_dialog_answer import call, wait_for
from tests.rig.test_dialog_multiq import Q3


def test_first_answer_moves_to_the_next_question(rig_slot: RigSlot, tmp_path) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    shots = Path(os.environ["MULTIQ_SHOTS"]) if os.environ.get("MULTIQ_SHOTS") else None
    with ScriptedModel([Step("RIG:q3", "AskUserQuestion", Q3)]) as model, sync_playwright() as pw:
        cdir, cwork = tmp_path / "ccfg", tmp_path / "cw"
        cwork.mkdir()
        seed_claude_config(cdir, cwork)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        name = rig_slot.create_session("rigadv", "rigclaude", cwork)
        rig_slot.wait_for(name, "❯")
        rig_slot.type_line(name, "RIG:q3 go")
        rig_slot.wait_for(name, "Best hacker movie?")
        wait_for(lambda: call(rig_slot, "GET", "/api/v1/approvals")[1]["items"], "server never listed the dialog", timeout=30)
        rig_slot.pin_rail()
        browser = pw.chromium.launch()
        ctx = browser.new_context(storage_state=rig_slot.slot.auth, viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(rig_slot.slot.base + "/")
        page.wait_for_timeout(1500)
        if page.locator(".modal-overlay[role=dialog]").count():
            page.keyboard.press("Escape")
            expect(page.locator(".modal-overlay[role=dialog]")).to_have_count(0)
        open_questions(page)
        cell = page.locator("[data-dq-cell]").first
        expect(cell).to_be_visible(timeout=20000)
        expect(cell.locator("[data-approval-step]")).to_have_text("question 1 of 3")
        strip = cell.locator("[data-approval-tabs]")
        text = strip.inner_text()
        assert "[ ]" not in text and "[x]" not in text, text
        if shots:
            shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots / "advance-1.png"))
        with page.expect_response(lambda r: r.url.endswith("/dialog/answer") and r.request.method == "POST") as posted:
            cell.locator(".ap-actions .modal-btn-secondary", has_text="The Matrix").click()
        assert posted.value.status == 200
        items = call(rig_slot, "GET", "/api/v1/approvals")[1]["items"]
        assert [i["question"] for i in items] == ["Which bands?"], items
        later = page.locator("[data-dq-cell]")
        expect(later).to_have_count(1, timeout=15000)
        expect(later.first.locator(".ap-question")).to_have_text("Which bands?", timeout=15000)
        expect(later.first.locator("[data-qc-toggle]")).to_have_attribute("aria-expanded", "true")
        expect(later.first.locator("[data-approval-step]")).to_have_text("question 2 of 3")
        if shots:
            page.screenshot(path=str(shots / "advance-2.png"))
        browser.close()
