
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.helpers.scripted_model import ScriptedModel, Step
from tests.helpers.scripted_model.rig import RigSlot, binary_missing, claude_script, open_questions, seed_claude_config
from tests.rig.test_approvals_inbox_ui import set_theme
from tests.rig.test_dialog_answer import call, session_id, wait_for
from tests.rig.test_dialog_multiq import Q3

THEMES = Path(__file__).resolve().parents[2] / "client" / "css" / "themes"
PICKS = [("matrix", "carnivore"), ("carnivore", "matrix"), ("dracula", "carnivore")]


def theme_fg_rgb(theme: str) -> str:
    manifest = json.loads((THEMES / theme / "theme.json").read_text())
    found = _deep(manifest)
    h = found.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(h[i:i + 2], 16) for i in (0, 2, 4)))


def _deep(node):
    if isinstance(node, dict):
        if "--color-fg" in node:
            return node["--color-fg"]
        for v in node.values():
            hit = _deep(v)
            if hit:
                return hit
    return None


@pytest.mark.parametrize("pinned,global_theme", PICKS)
def test_card_text_is_the_pinned_theme_foreground(rig_slot: RigSlot, tmp_path, pinned: str, global_theme: str) -> None:
    if binary_missing("claude"):
        pytest.skip(binary_missing("claude"))
    want = theme_fg_rgb(pinned)
    set_theme(rig_slot, global_theme)
    shots = Path(os.environ["MULTIQ_SHOTS"]) if os.environ.get("MULTIQ_SHOTS") else None
    with ScriptedModel([Step("RIG:q3", "AskUserQuestion", Q3)]) as model, sync_playwright() as pw:
        cdir, cwork = tmp_path / "ccfg", tmp_path / "cw"
        cwork.mkdir()
        seed_claude_config(cdir, cwork)
        rig_slot.register_wrapper("rigclaude", "claude", claude_script(model.url, cdir))
        name = rig_slot.create_session("rigct", "rigclaude", cwork)
        status, _ = call(rig_slot, "PATCH", f"/api/v1/sessions/{name}/theme", {"theme_id": pinned})
        assert status == 200
        rig_slot.wait_for(name, "❯")
        rig_slot.type_line(name, "RIG:q3 go")
        rig_slot.wait_for(name, "Best hacker movie?")
        wait_for(lambda: call(rig_slot, "GET", "/api/v1/approvals")[1]["items"], "server never listed the dialog", timeout=30)
        rig_slot.pin_rail()
        browser = pw.chromium.launch()
        ctx = browser.new_context(storage_state=rig_slot.slot.auth, viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(rig_slot.slot.base + "/")
        open_questions(page)
        cell = page.locator("[data-dq-cell]").first
        expect(cell).to_be_visible(timeout=20000)
        expect(cell.locator("[data-approval-step]")).to_have_text("question 1 of 3")
        labels = cell.locator(".ap-opt-label")
        expect(labels).to_have_count(4)
        expect(cell.locator(".ap-note")).to_have_count(4)
        colours = cell.evaluate(
            """el => { const c = s => [...el.querySelectorAll(s)].map(n => getComputedStyle(n).color);
                 return {question: c('.ap-question'), label: c('.ap-opt-label'), desc: c('.ap-note'), tab: c('.ap-tab--done, .ap-tab')}; }""")
        for kind in ("question", "label", "desc"):
            assert colours[kind] and all(col == want for col in colours[kind]), (pinned, kind, want, colours[kind])
        assert theme_fg_rgb(global_theme) != want
        if shots:
            shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots / f"multiq-{pinned}.png"))
        browser.close()
