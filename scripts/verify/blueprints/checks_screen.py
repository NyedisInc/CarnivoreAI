
from __future__ import annotations

from scripts.lib.verify_harness import dismiss_offers
from scripts.verify.blueprints.env import Env
from scripts.verify.blueprints.page_helpers import (
    SCREEN_SEL, click_text, fill_session_zero, opened_blueprints, row_for,
)


def check_screen_empty(env: Env) -> None:
    args, page, report = env.args, env.page, env.report
    opened_blueprints(page, args.base)
    report.check(page.locator(SCREEN_SEL).count() == 1, "12a. the blueprints screen opens on #blueprints")
    report.check(page.locator("body.session-sidebar-pinned").count() == 1,
                 "D1-pre. the agents drawer is pinned open for this check")
    box = page.locator(SCREEN_SEL).bounding_box()
    head_box = page.locator(f'{SCREEN_SEL} .mgr__head').first.bounding_box()
    report.check(bool(head_box) and head_box["x"] >= 300,
                 "D1. the screen's content starts clear of the pinned drawer's 320px", str(head_box))
    report.check(bool(box) and box["y"] > 0,
                 "D2. the screen starts below the top bar, not at y=0", str(box))
    search = page.locator(f'{SCREEN_SEL} .mgr__input').first
    search.click(timeout=4000)
    report.check(search.evaluate("el => el === document.activeElement"),
                 "D1. the search field is actually clickable, not covered by the drawer")


def check_escape_closes_dialog_then_screen(env: Env) -> None:
    args, page, report, tag = env.args, env.page, env.report, env.tag
    opened_blueprints(page, args.base)
    bp_name = f"vlbp {tag}"
    if row_for(page, bp_name).count() == 0:
        report.check(False, "D4. escape: no blueprint left to open a launch dialog against")
        return
    click_text(page, row_for(page, bp_name), "launch")
    page.locator(".bp-launch__member, .bp-launch__error").first.wait_for(state="visible", timeout=8000)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    report.check(page.locator(".modal-overlay:visible").count() == 0,
                 "D4. one Escape closes the launch dialog")
    report.check(page.locator(SCREEN_SEL).count() == 1,
                 "D4. ...and leaves the blueprints screen open underneath")
    for _ in range(3):
        if page.locator(SCREEN_SEL).count() == 0:
            break
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    report.check(page.locator(SCREEN_SEL).count() == 0,
                 "D4. a second Escape then closes the screen")


def check_screen_closes_on_drawer_navigation(env: Env) -> None:
    args, page, report = env.args, env.page, env.report
    opened_blueprints(page, args.base)
    row = page.locator(".session-sidebar-row[data-session-id]").first
    if row.count() == 0:
        report.check(False, "D3. drawer navigation: no session row to click")
        return
    row.click()
    page.wait_for_timeout(1000)
    report.check(page.locator(SCREEN_SEL).count() == 0,
                 "D3. the blueprints screen closes when the drawer navigates away")


def check_editor_shows_real_error_text(env: Env) -> None:
    args, page, report, tag, existing_dir = env.args, env.page, env.report, env.tag, env.existing_dir
    opened_blueprints(page, args.base)
    existing_name = f"vlbp {tag}"
    if row_for(page, existing_name).count() == 0:
        report.check(False, "D5. no existing blueprint left to collide with")
        return
    click_text(page, page.locator(SCREEN_SEL), "new blueprint")
    page.locator("#bp-name").wait_for(state="visible", timeout=4000)
    page.fill("#bp-name", existing_name)
    fill_session_zero(page, label="clash", family="shell", mode="existing", path=str(existing_dir))
    click_text(page, page.locator(".modal-content"), "save")
    page.locator(".bp-editor__error").wait_for(state="visible", timeout=4000)
    error_text = page.locator(".bp-editor__error").inner_text().lower()
    report.check("answered" not in error_text and "exist" in error_text,
                 "D5. a name clash on save shows the real sentence, never a generic "
                 "\"the server answered ###\"", error_text)
    page.locator('.modal-content button:has-text("cancel")').first.click()
    page.wait_for_timeout(300)


def check_plus_menu_blueprint_flyout(env: Env) -> None:
    args, page, report, server, tag, layout_row_state = env.args, env.page, env.report, env.server, env.tag, env.layout_row_state
    uuid = layout_row_state.get("uuid")
    bp_name = f"vlbp {tag}"
    if not uuid or not server.call("GET", "/blueprints").get("blueprints"):
        report.check(False, "V4. plus-menu: no seeded Layout or saved blueprint to check against")
        return
    page.goto(args.base + f"/layout/{uuid}", wait_until="domcontentloaded")
    dismiss_offers(page)
    page.wait_for_timeout(800)
    plus = page.locator(".oc-tab-new").first
    plus.wait_for(state="visible", timeout=8000)
    plus.click()
    page.locator('.acm-menu[data-level="0"]').wait_for(state="visible", timeout=4000)
    page.locator('.acm-menu[data-level="0"] button[data-node="blueprint"]').click()
    branch_item = page.locator(f'.acm-menu[data-level="1"] button:has-text("{bp_name}")')
    report.check(branch_item.count() > 0,
                 "V4. the saved blueprint is listed in the \"+\" menu's blueprint branch")
    if branch_item.count() == 0:
        return
    branch_item.first.click()
    page.locator(".bp-launch__member, .bp-launch__error").first.wait_for(state="visible", timeout=8000)
    report.check(page.locator(".modal-overlay:visible").count() == 1,
                 "V4. clicking a blueprint in the \"+\" menu opens its launch dialog directly")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
