
from __future__ import annotations

import pytest

from scripts.widgets import harness

MENU_LOOK = """() => {
    const menu = document.querySelector('[role="menu"]:popover-open');
    if (!menu) return null;
    const style = getComputedStyle(menu);
    const ground = /rgb\\((\\d+), (\\d+), (\\d+)\\)/.exec(style.backgroundImage) || /rgb\\((\\d+), (\\d+), (\\d+)\\)/.exec(style.backgroundColor);
    return { rgb: ground ? ground.slice(1, 4).map(Number) : null, image: style.backgroundImage, shadow: style.boxShadow, cls: menu.className };
}"""
DARK_THEMES = ("carnivore", "blade_runner")


def luminance(rgb: list[int]) -> float:
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255


@pytest.mark.parametrize("theme", DARK_THEMES)
def test_the_notes_menu_opens_on_the_themed_popup_surface(page_and_base, theme: str) -> None:
    page, base = page_and_base
    page.set_viewport_size({"width": 1600, "height": 1100})
    opened = harness.open_widget(page, base, "core.notes", "data", {"zone": "home", "size": "m", "theme": theme}, extra={"state": "menu"})
    assert opened.error == "", opened.error
    look = page.evaluate(MENU_LOOK)
    assert look is not None, "the menu-open scenario left no open menu"
    assert "popup-focus" in look["cls"]
    assert look["rgb"] is not None and luminance(look["rgb"]) < 0.3, f"the menu ground is not the dark theme's: {look}"
    assert "linear-gradient" in look["image"] and look["shadow"] != "none", look


def test_without_the_sheet_the_same_menu_is_a_white_box_so_the_check_can_fail(page_and_base) -> None:
    page, base = page_and_base
    page.set_viewport_size({"width": 1600, "height": 1100})
    harness.open_widget(page, base, "core.notes", "data", {"zone": "home", "size": "m", "theme": "carnivore"}, extra={"state": "menu"})
    assert luminance(page.evaluate(MENU_LOOK)["rgb"]) < 0.3
    page.evaluate("() => document.querySelectorAll('link[href*=\"popup-focus\"]').forEach((link) => link.remove())")
    bare = page.evaluate(MENU_LOOK)
    assert bare["image"] == "none" and bare["shadow"] == "none"
    assert luminance(bare["rgb"]) > 0.9, bare


def test_the_page_links_the_sheet_last(page_and_base) -> None:
    page, base = page_and_base
    harness.open_widget(page, base, "core.notes", "data", {"zone": "home", "size": "m", "theme": "carnivore"})
    hrefs = page.evaluate("() => [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => new URL(l.href).pathname)")
    assert hrefs[-1] == "/static/css/popup-focus.css", hrefs
