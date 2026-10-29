
from __future__ import annotations

from typing import Any

Page = Any

ACCOUNT_CHIP = '[data-bar-action="account"]'
EDIT_LAYOUT_ITEM = '.acm-menu [data-node="layout"]'
EDITOR_DRAWER = "[data-layout-editor-drawer]"
EDITOR_DONE = "[data-layout-editor-done]"
PICKER_FOLDS = ("session", "terminal")
LAYOUT_NAME_MODAL = "[data-layout-name-modal]"
PICKER_REFUSAL = ".le-wfold__refusal"
ADDED, MODAL_OPEN, REFUSED, MISSING = "added", "modal-open", "refused", "missing"
_OPEN_SIDEBAR_JS = "() => window.SessionSidebar && window.SessionSidebar.open && window.SessionSidebar.open()"
_ACTIVE_JS = "() => !!(window.CloudeWeb && window.CloudeWeb.layoutEditor && window.CloudeWeb.layoutEditor.active())"


def open_account_menu(page: Page) -> None:
    page.evaluate(_OPEN_SIDEBAR_JS)
    page.locator(ACCOUNT_CHIP).first.click()


def edit_layout_offered(page: Page) -> bool:
    open_account_menu(page)
    page.wait_for_timeout(300)
    item = page.locator(EDIT_LAYOUT_ITEM)
    offered = item.count() == 1 and item.first.get_attribute("aria-disabled") != "true"
    page.keyboard.press("Escape")
    return offered


def editor_active(page: Page) -> bool:
    return bool(page.evaluate(_ACTIVE_JS))


def name_modal_up(page: Page) -> bool:
    return page.locator(LAYOUT_NAME_MODAL).count() > 0


def open_edit_layout(page: Page) -> None:
    if not editor_active(page):
        open_account_menu(page)
        page.locator(EDIT_LAYOUT_ITEM).first.click()
    try:
        page.locator(EDITOR_DRAWER).first.wait_for(state="visible", timeout=10000)
    except Exception:  # noqa: BLE001
        finish_edit_layout(page)
        raise


def finish_edit_layout(page: Page) -> None:
    if editor_active(page) and not name_modal_up(page):
        page.locator(EDITOR_DONE).first.click()
        page.wait_for_timeout(400)


def pick_in_folds(page: Page, member: dict) -> str:
    for kind in PICKER_FOLDS:
        entry = page.locator(f'[data-picker-entry="{kind}"]').first
        if entry.get_attribute("aria-expanded") != "true":
            entry.click()
            page.wait_for_timeout(300)
        row = page.locator(f'[data-picker-row="{member["id"]}"]')
        if row.count() and row.first.get_attribute("aria-disabled") != "true":
            row.first.click()
            page.wait_for_timeout(1200)
            if name_modal_up(page):
                return MODAL_OPEN
            return REFUSED if page.locator(PICKER_REFUSAL).count() else ADDED
    return MISSING


def add_window(page: Page, member: dict) -> str:
    open_edit_layout(page)
    try:
        return pick_in_folds(page, member)
    finally:
        finish_edit_layout(page)
