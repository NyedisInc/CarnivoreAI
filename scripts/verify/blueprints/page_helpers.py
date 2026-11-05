
from __future__ import annotations

from typing import TYPE_CHECKING

import subprocess
from pathlib import Path

from scripts.lib.verify_harness import dismiss_offers

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

SCREEN_SEL = '.mgr[aria-label="blueprints"]'




def make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "-b", "master", str(repo)], check=True)
    (repo / "README.md").write_text("verify\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "--quiet", "-m", "seed"],
        check=True,
    )
    return repo


def open_drawer(page: Page) -> None:
    claw = page.locator('[data-rail="claw"]')
    btn = page.locator("#session-sidebar-toggle")
    try:
        if claw.count() and claw.first.is_visible():
            claw.first.click()
            page.wait_for_timeout(200)
        elif btn.count() and btn.first.is_visible():
            btn.first.click()
            page.wait_for_timeout(200)
    except Exception:  # noqa: BLE001
        pass


def close_any_modal(page: Page) -> None:
    for _ in range(3):
        if page.locator(".modal-overlay:visible").count() == 0:
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)


def opened_blueprints(page: Page, base: str) -> None:
    close_any_modal(page)
    page.goto(base + "/#blueprints", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    dismiss_offers(page)
    open_drawer(page)
    page.locator(SCREEN_SEL).wait_for(state="visible", timeout=20000)


def click_text(page: Page, root: Page | Locator, text: str):
    loc = root.locator(f'button:has-text("{text}")').first
    loc.click()
    return loc


def row_for(page: Page, name: str):
    return page.locator(f'.mgr-card:has(.mgr-card__name:text-is("{name}"))').first


def open_detail(page: Page, name: str):
    row_for(page, name).locator(".mgr-card__name").click()
    page.locator(".mgr__detail").wait_for(state="visible", timeout=4000)


def fill_session_zero(page: Page, *, label: str, family: str, mode: str, path: str = "",
                       repo: str = "", base_branch: str = "", branch: str = "",
                       skill: str = "", prompt: str = "") -> None:
    page.fill("#bp-session-0-label", label)
    page.select_option("#bp-session-0-family", family)
    if mode == "worktree":
        page.get_by_label("new git worktree").check()
        page.fill("#bp-session-0-repo", repo)
        page.fill("#bp-session-0-base", base_branch)
        page.fill("#bp-session-0-branch", branch)
    else:
        page.fill("#bp-session-0-path", path)
    if skill:
        page.fill("#bp-session-0-skill-input", skill)
        click_text(page, page, "add skill")
    if prompt:
        page.fill("#bp-session-0-prompt", prompt)
