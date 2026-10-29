
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect, sync_playwright

from tests.helpers.scripted_model.rig import RigSlot

THEMES = ("carnivore", "dracula", "matrix")
HANDLE_X = 5
STATE = "document.querySelector('.sbr-shell').dataset.railState"


def _open_page(pw, rig_slot: RigSlot, theme: str) -> Page:
    prefs = rig_slot.slot.api("GET", "/api/v1/preferences")
    rig_slot.slot.api("PATCH", "/api/v1/preferences", {"changes": {"theme": theme}, "expected_revision": prefs["revision"]})
    ctx = pw.chromium.launch().new_context(storage_state=rig_slot.slot.auth, viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(rig_slot.slot.base + "/")
    page.wait_for_selector(".sbr-shell", timeout=20000)
    page.wait_for_timeout(1500)
    if page.locator(".modal-overlay[role=dialog]").count():
        page.keyboard.press("Escape")
    expect(page.locator(".sbr-shell")).to_have_attribute("data-rail-state", "handle")
    return page


def _peek(page: Page) -> None:
    page.mouse.move(700, 500, steps=3)
    page.wait_for_timeout(500)
    page.mouse.move(HANDLE_X, 300, steps=4)
    expect(page.locator(".sbr-shell")).to_have_attribute("data-rail-state", "peek")
    expect(page.locator(".sbr-flyout--open")).to_have_count(1)
    page.wait_for_timeout(400)


def test_a_leave_under_a_still_pointer_does_not_close_the_rail(rig_slot: RigSlot) -> None:
    with sync_playwright() as pw:
        page = _open_page(pw, rig_slot, "carnivore")
        for round_ in range(6):
            _peek(page)
            target = "'.sbr-shell'" if round_ % 2 == 0 else "'#session-sidebar-flyout'"
            page.evaluate(f"document.querySelector({target}).dispatchEvent(new PointerEvent('pointerleave', {{pointerType: 'mouse'}}))")
            page.wait_for_timeout(900)
            assert page.evaluate(STATE) == "peek", f"round {round_}: the rail slid away under a still pointer"
            expect(page.locator(".sbr-flyout--open")).to_have_count(1)
            page.mouse.move(HANDLE_X + 1, 310, steps=2)
            page.wait_for_timeout(300)
            assert page.evaluate(STATE) == "peek"
            page.mouse.move(700, 500, steps=3)
            expect(page.locator(".sbr-shell")).to_have_attribute("data-rail-state", "handle", timeout=3000)


@pytest.mark.parametrize("theme", THEMES)
def test_the_menu_covers_the_providers_area_and_the_stats_strip(rig_slot: RigSlot, theme: str) -> None:
    with sync_playwright() as pw:
        page = _open_page(pw, rig_slot, theme)
        _peek(page)
        rects = page.evaluate(
            """() => {
              const r = (s) => { const e = document.querySelector(s); const b = e && e.getBoundingClientRect(); return b && b.height > 0 ? {x: b.x, y: b.y, w: b.width, h: b.height} : null; };
              return {ledger: r('#session-sidebar-ledger'), bar: r('#session-sidebar-bar-slot'), stats: r('#session-sidebar-stats'), flyout: r('.sbr-flyout--open')};
            }"""
        )
        assert rects["ledger"], "the providers area is not drawn on the slot, so nothing was measured"
        x = rects["flyout"]["x"] + rects["flyout"]["w"] / 2
        covered = "(a) => document.elementFromPoint(a[0], a[1])?.closest('.sbr-flyout--open') !== null"
        for label, y in (("top", rects["ledger"]["y"] + 2), ("middle", rects["ledger"]["y"] + rects["ledger"]["h"] / 2), ("bottom", rects["ledger"]["y"] + rects["ledger"]["h"] - 2)):
            assert page.evaluate(covered, [x, y]), f"{theme}: the menu does not cover the providers area ({label})"
        if rects["stats"]:
            assert page.evaluate(covered, [x, rects["stats"]["y"] + rects["stats"]["h"] / 2]), f"{theme}: the menu does not cover the stats strip"
        if rects["bar"]:
            assert not page.evaluate(covered, [x, rects["bar"]["y"] + rects["bar"]["h"] / 2]), f"{theme}: the menu covers the bottom bar"
