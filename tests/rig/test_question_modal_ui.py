
from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import RigSlot, binary_missing, claude_script, seed_claude_config
from tests.rig.test_approvals_inbox_ui import set_theme
from tests.rig.test_dialog_answer import call, tool_results, wait_for
from tests.rig.test_dialog_multiq import Q3

MODAL = "[data-approval-inbox]"
THEMES = ("carnivore", "matrix", "blade_runner")


def open_modal(page, sid: str) -> None:
    page.wait_for_function("() => !!(window.CloudeWeb && window.CloudeWeb.openApprovalFor)")
    assert page.evaluate("id => window.CloudeWeb.openApprovalFor(id)", sid) == "opened"
    expect(page.locator("[data-ask-form]")).to_be_visible()


def stage_ask(rig_slot: RigSlot, tmp_path, model: ScriptedModel, tag: str, first_question: str, count: int) -> tuple[str, str]:
    cdir, cwork = tmp_path / "ccfg", tmp_path / "cw"
    cwork.mkdir()
    seed_claude_config(cdir, cwork)
    rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
    (rig_slot.slot.dir / "home").mkdir(parents=True, exist_ok=True)
    (rig_slot.slot.dir / "home" / ".claude").symlink_to(cdir)
    name = rig_slot.create_session("rigmodal", "rigclaude", cwork)
    rig_slot.wait_for(name, "❯")
    rig_slot.type_line(name, f"{tag} go")
    rig_slot.wait_for(name, first_question)
    wait_for(lambda: call(rig_slot, "GET", "/api/v1/approvals")[1]["items"], "server never listed the dialog", timeout=30)
    wait_for(lambda: call(rig_slot, "GET", "/api/v1/approvals")[1]["items"][0]["questions_state"] == "matched",
             "the server never matched the transcript's questions to the pane: "
             + str({k: v for k, v in call(rig_slot, "GET", "/api/v1/approvals")[1]["items"][0].items() if k.startswith("question")})
             + str(list((cdir / "projects").rglob("*.jsonl"))), timeout=60)
    item = call(rig_slot, "GET", "/api/v1/approvals")[1]["items"][0]
    assert item["questions_state"] == "matched" and len(item["questions"]) == count, item.get("questions_state")
    return name, item["session_id"]


def test_fill_all_tabs_submit_once_and_it_closes(rig_slot: RigSlot, tmp_path) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    shots = Path(os.environ["C3_SHOTS"]) if os.environ.get("C3_SHOTS") else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    with ScriptedModel([Step("RIG:q3", "AskUserQuestion", Q3)]) as model, sync_playwright() as pw:
        name, sid = stage_ask(rig_slot, tmp_path, model, "RIG:q3", "Best hacker movie?", 3)

        browser = pw.chromium.launch()
        accents: dict[str, str] = {}
        for theme in THEMES:
            set_theme(rig_slot, theme)
            for width, height in ((1440, 900), (390, 844)):
                ctx = browser.new_context(storage_state=rig_slot.slot.auth, viewport={"width": width, "height": height})
                page = ctx.new_page()
                page.goto(rig_slot.slot.base + "/")
                open_modal(page, sid)
                expect(page.locator(".ak-tabs [role=tab]")).to_have_count(3)
                page.wait_for_timeout(2500)
                accents[theme] = page.evaluate(
                    "() => getComputedStyle(document.querySelector('.modal-content')).getPropertyValue('--oc-orange').trim()")
                box = page.locator(".modal-content").bounding_box()
                assert box and abs((box["x"] + box["width"] / 2) - width / 2) < 3, "the modal is centered"
                if shots:
                    page.screenshot(path=str(shots / f"modal-{theme}-{width}.png"))
                ctx.close()

        assert len(set(accents.values())) == len(THEMES), accents
        set_theme(rig_slot, "carnivore")
        ctx = browser.new_context(storage_state=rig_slot.slot.auth, viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(rig_slot.slot.base + "/")
        open_modal(page, sid)
        modal = page.locator(MODAL)
        page.locator("[data-ask-option='The Matrix']").click()
        page.locator(".ak-tabs [data-tab='1']").click()
        page.locator("[data-ask-option='Pantera']").click()
        page.locator("[data-ask-option='Slayer']").click()
        expect(page.locator(".ak-tabs [data-tab='2'] .oc-ptab__badge")).to_have_text("unanswered")
        expect(page.locator("[data-ask-left]")).to_contain_text("1 unanswered, left out")
        if shots:
            page.screenshot(path=str(shots / "modal-filled-carnivore-1440.png"))
        assert "The Matrix" not in tool_results(model)
        with pytest.raises(AssertionError):
            expect(page.locator("[data-ask-form]")).to_have_count(0, timeout=500)
        page.locator("[data-ask-submit]").click()
        wait_for(lambda: all(w in tool_results(model) for w in ("The Matrix", "Pantera", "Slayer")),
                 "the model never saw the answers; modal said " + " | ".join(page.locator("[data-approval-notice]").all_inner_texts())
                 + "\n" + rig_slot.capture(name), 60)
        assert "Pizza" not in tool_results(model) and "Coffee" not in tool_results(model)
        expect(modal).to_have_count(0, timeout=20000)
        browser.close()


TEXTY = {"questions": [
    {"question": "Name the box?", "header": "Name", "multiSelect": False,
     "options": [{"label": "alpha", "description": "first"}, {"label": "beta", "description": "second"}]},
    {"question": "Which flags?", "header": "Flags", "multiSelect": True,
     "options": [{"label": "fast", "description": "quick"}, {"label": "safe", "description": "careful"}]},
    {"question": "Which layout?", "header": "Layout", "multiSelect": False,
     "options": [{"label": "Wide", "description": "w", "preview": "[ wide ]"},
                 {"label": "Tall", "description": "t", "preview": "[ tall ]"}]}]}


def test_other_text_multi_select_and_notes_reach_the_model(rig_slot: RigSlot, tmp_path) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    with ScriptedModel([Step("RIG:texty", "AskUserQuestion", TEXTY)]) as model, sync_playwright() as pw:
        name, sid = stage_ask(rig_slot, tmp_path, model, "RIG:texty", "Name the box?", 3)
        browser = pw.chromium.launch()
        ctx = browser.new_context(storage_state=rig_slot.slot.auth, viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(rig_slot.slot.base + "/")
        open_modal(page, sid)
        page.locator("[data-ask-other]").fill("2 fish")
        page.locator(".ak-tabs [data-tab='1']").click()
        page.locator("[data-ask-option='fast']").click()
        page.locator("[data-ask-option='safe']").click()
        page.locator("[data-ask-other]").fill("/exit later")
        page.locator(".ak-tabs [data-tab='2']").click()
        page.locator("[data-ask-option='Tall']").click()
        page.locator("[data-ask-notes]").fill("1 note")
        page.locator("[data-ask-submit]").click()
        wait_for(lambda: all(w in tool_results(model) for w in ("2 fish", "fast", "safe", "/exit later", "Tall", "1 note")),
                 "the model never saw every typed answer: " + tool_results(model) + "\n" + rig_slot.capture(name), 90)
        assert "alpha" not in tool_results(model) and "beta" not in tool_results(model)
        expect(page.locator(MODAL)).to_have_count(0, timeout=20000)
        browser.close()


def _lone(preview: bool) -> dict:
    opts = ([{"label": "Wide", "description": "w", "preview": "[ wide ]"}, {"label": "Tall", "description": "t", "preview": "[ tall ]"}]
            if preview else [{"label": "alpha", "description": "first"}, {"label": "beta", "description": "second"}])
    return {"questions": [{"question": "Lone layout?" if preview else "Lone name?", "header": "Lone", "multiSelect": False, "options": opts}]}


LONG_OTHER = "long other " + " ".join(f"w{i:03d}" for i in range(60))


@pytest.mark.parametrize("case,preview,typed", [
    ("digit1", False, "1 lone digit"),
    ("digit2", False, "2 lone digit"),
    ("slash", False, "/exit lone"),
    ("long", False, LONG_OTHER),
    ("notes", True, "9 lone notes"),
])
def test_lone_single_select_text_reaches_the_model_exactly(rig_slot: RigSlot, tmp_path, case: str, preview: bool, typed: str) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    assert len(LONG_OTHER.encode()) > 256
    tag = f"RIG:lone{case}"
    ask = _lone(preview)
    with ScriptedModel([Step(tag, "AskUserQuestion", ask)]) as model, sync_playwright() as pw:
        name, sid = stage_ask(rig_slot, tmp_path, model, tag, ask["questions"][0]["question"], 1)
        browser = pw.chromium.launch()
        ctx = browser.new_context(storage_state=rig_slot.slot.auth, viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(rig_slot.slot.base + "/")
        open_modal(page, sid)
        if preview:
            page.locator("[data-ask-option='Tall']").click()
            page.locator("[data-ask-notes]").fill(typed)
        else:
            page.locator("[data-ask-other]").fill(typed)
        page.locator("[data-ask-submit]").click()
        wait_for(lambda: typed in tool_results(model),
                 "the model never saw the exact text: " + tool_results(model) + "\n" + rig_slot.capture(name), 90)
        got = tool_results(model)
        if os.environ.get("Q_EVIDENCE"):
            Path(os.environ["Q_EVIDENCE"]).open("a").write(f"[{case}] typed={typed!r}\n[{case}] received={got!r}\n")
        assert got.count(typed) == 1, got
        assert "alpha" not in got and "beta" not in got and ("Tall" in got) == preview
        expect(page.locator(MODAL)).to_have_count(0, timeout=20000)
        browser.close()
