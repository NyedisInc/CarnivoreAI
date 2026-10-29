
from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect, sync_playwright

from tests.helpers.scripted_model.rig import RigSlot

STRIPS = {
    "side": ("#session-widget-rail", "data-bar-state"),
    "bottom": ("#session-widget-rail-bottom", "data-bar-state"),
    "rail": (".sbr-shell", "data-rail-state"),
}
PINS = {
    "side": "#session-widget-rail [data-bar-pin]",
    "bottom": "#session-widget-rail-bottom [data-bar-pin]",
    "rail": ".oc-nav-pin [data-bar-pin]",
}
SHOTS = os.environ.get("SHOTS_DIR")


def _open_page(pw, rig_slot: RigSlot) -> Page:
    rig_slot.slot.api("POST", "/api/v1/sessions", {
        "project_name": "barhover", "working_dir": "~", "agent_type": "shell", "auto_start_claude": True, "copy_templates": False})
    ctx = pw.chromium.launch().new_context(storage_state=rig_slot.slot.auth, viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(rig_slot.slot.base + "/")
    page.wait_for_selector(".sbr-shell", timeout=20000)
    page.wait_for_timeout(1500)
    if page.locator(".modal-overlay[role=dialog]").count():
        page.keyboard.press("Escape")
    page.get_by_text("barhover").first.click()
    page.wait_for_selector("#session-widget-rail", timeout=20000)
    page.wait_for_timeout(800)
    return page


def _state(page: Page, name: str) -> str:
    sel, attr = STRIPS[name]
    return page.locator(sel).first.get_attribute(attr) or ""


def _handle_point(page: Page, name: str) -> tuple[float, float]:
    box = page.locator(f"{STRIPS[name][0]} [data-bar-handle]").first.bounding_box()
    assert box, f"{name}: the handle is not drawn"
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _away(page: Page) -> None:
    page.mouse.move(720, 450, steps=3)


def _shot(page: Page, name: str, what: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"{name}-{what}.png"))


@pytest.mark.parametrize("name", list(STRIPS))
def test_hover_opens_the_pin_keeps_it_open_click_still_toggles(rig_slot: RigSlot, name: str) -> None:
    sel, attr = STRIPS[name]
    with sync_playwright() as pw:
        page = _open_page(pw, rig_slot)
        _away(page)
        page.wait_for_timeout(600)
        assert _state(page, name) == "handle", f"{name}: not a closed handle at rest"

        x, y = _handle_point(page, name)
        page.mouse.move(x, y, steps=4)
        expect(page.locator(sel).first).to_have_attribute(attr, "peek", timeout=3000)
        page.wait_for_timeout(400)
        _shot(page, name, "peek")
        pin = page.locator(PINS[name]).first
        expect(pin).to_be_visible()

        _away(page)
        expect(page.locator(sel).first).to_have_attribute(attr, "handle", timeout=3000)

        page.mouse.move(x, y, steps=4)
        expect(page.locator(sel).first).to_have_attribute(attr, "peek", timeout=3000)
        page.wait_for_timeout(400)
        pin.click()
        expect(page.locator(sel).first).to_have_attribute(attr, "pinned", timeout=3000)
        expect(pin).to_have_attribute("aria-pressed", "true")
        _away(page)
        page.wait_for_timeout(1200)
        assert _state(page, name) == "pinned", f"{name}: a pinned strip retracted"
        _shot(page, name, "pinned")

        pin.click()
        expect(pin).to_have_attribute("aria-pressed", "false")
        _away(page)
        expect(page.locator(sel).first).to_have_attribute(attr, "handle", timeout=3000)
        page.mouse.move(x, y, steps=4)
        expect(page.locator(sel).first).to_have_attribute(attr, "peek", timeout=3000)
        _away(page)
        expect(page.locator(sel).first).to_have_attribute(attr, "handle", timeout=3000)

        handle = page.locator(f"{sel} [data-bar-handle]").first
        handle.focus()
        page.keyboard.press("Enter")
        expect(page.locator(sel).first).to_have_attribute(attr, "peek", timeout=3000)
