
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import Any

from scripts.verify.agent_kebab.helpers import (
    Api, choose_first_direct_provider, click_cascade, click_native_item, click_scrolled, group_members,
    layout_members, open_row_kebab, row, seed_group, seed_layout, seed_session, sessions_under, wait_for,
)

SESSION_KEYS = ("s1", "s2", "s3", "s5", "s6", "s7", "s8", "s9", "s10")
VIEWPORT = {"width": 1600, "height": 1000}


class Tally:

    def __init__(self) -> None:
        self.passes = 0
        self.failures: list[str] = []

    def check(self, ok: bool, label: str) -> None:
        print(f"{'ok' if ok else 'FAIL'} {label}")
        if ok:
            self.passes += 1
        else:
            self.failures.append(label)


@dataclass
class Seeds:

    project: str
    path: str
    names: dict[str, dict]
    layout1: str
    layout2: str
    group1: str
    group2: str
    group3: str


@dataclass
class Master:

    base: str
    storage_state: str
    api: Api | None = None
    project: str = ""
    path: str = ""
    hover_name: str | None = None


@dataclass
class Run:

    args: argparse.Namespace
    api: Api
    seeds: Seeds
    master: Master | None
    tally: Tally
    browser: Any = None
    page: Any = None
    errors: list[str] = field(default_factory=list)

    def shot(self, page: Any, name: str) -> None:
        if self.args.shots:
            os.makedirs(self.args.shots, exist_ok=True)
            page.screenshot(path=os.path.join(self.args.shots, name))

    def master_page(self, track_errors: bool = False) -> tuple[Any, Any]:
        ctx = self.browser.new_context(viewport=VIEWPORT, storage_state=self.master.storage_state)
        page = ctx.new_page()
        if track_errors:
            page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(self.master.base + "/", wait_until="domcontentloaded")
        return ctx, page


def _scratch_project(api: Api, project: str, path: str, scratch_dirs: list[str]) -> None:
    os.makedirs(path, exist_ok=True)
    scratch_dirs.append(path)
    api.call("/projects", "POST", {"name": project, "path": path})
    api.ledger.record(f"/projects/{project}")


def _seed_slot(api: Api, stamp: str, scratch_dirs: list[str]) -> Seeds:
    project, path = f"kebab-verify-{stamp}", f"/tmp/kebab-verify-{stamp}"
    _scratch_project(api, project, path, scratch_dirs)
    names = {k: seed_session(api, project, path) for k in SESSION_KEYS}
    return Seeds(
        project=project, path=path, names=names,
        layout1=seed_layout(api, f"L1-{stamp}", [names["s5"]["row_id"], names["s6"]["row_id"]]),
        layout2=seed_layout(api, f"L2-{stamp}", [names["s8"]["row_id"], names["s9"]["row_id"]]),
        group1=seed_group(api, f"G1-{stamp}", []),
        group2=seed_group(api, f"G2-{stamp}", []),
        group3=seed_group(api, f"G3-{stamp}", [names["s7"]["name"]]),
    )


def _seed_master(args: argparse.Namespace, stamp: str, extra_apis: list[Api], scratch_dirs: list[str]) -> Master | None:
    if not (args.master_base and args.master_storage_state):
        return None
    master = Master(args.master_base, args.master_storage_state)
    try:
        master.api = Api(args.master_base, args.master_storage_state)
        extra_apis.append(master.api)
        master.project, master.path = f"kebab-verify-master-{stamp}", f"/tmp/kebab-verify-master-{stamp}"
        _scratch_project(master.api, master.project, master.path, scratch_dirs)
        master.hover_name = seed_session(master.api, master.project, master.path)["name"]
    except Exception as exc:  # noqa: BLE001
        print(f"skip 5-neg (could not seed on --master-base: {exc})")
    return master


def check_1_project_kebab_new_agent(run: Run) -> None:
    page, check, api, sd = run.page, run.tally.check, run.api, run.seeds
    picker = page.locator(".modal-overlay.na-flow")
    before = len(sessions_under(api, sd.path))
    heading_kebab = page.locator(
        f'.session-sidebar-group__headerrow:has-text("{sd.project}") [data-project-menu]').first
    click_scrolled(page, heading_kebab)
    first_item = page.locator('#item-menu-host [role^="menuitem"]').first
    check(wait_for(page, lambda: first_item.count() > 0, 4000)
          and (first_item.inner_text() or "").strip().lower() == "new agent",
          '1a the project kebab\'s first item is "new agent"')
    first_item.click()
    check(wait_for(page, lambda: picker.count() > 0, 4000)
          and "select provider" in (picker.locator(".text-prompt-modal__verb").first.inner_text() or "").lower(),
          '1b clicking it opens the "select provider" picker rather than launching')
    check(len(sessions_under(api, sd.path)) == before, "1c the picker opening created no session yet")
    page.keyboard.press("Escape")
    check(wait_for(page, lambda: picker.count() == 0, 4000), "1d Esc closes the picker")
    check(len(sessions_under(api, sd.path)) == before, "1e Esc/cancel launched nothing")

    click_scrolled(page, heading_kebab)
    page.locator('#item-menu-host [role^="menuitem"]').first.click()
    check(wait_for(page, lambda: picker.count() > 0, 4000), "1f reopening shows the picker again")
    check(choose_first_direct_provider(page), "1g a provider row is clickable")
    check(wait_for(page, lambda: len(sessions_under(api, sd.path)) == before + 1, 10000),
          "1h choosing a provider launches exactly one new session, under the project's own folder")
    check(wait_for(page, lambda: picker.count() == 0, 4000),
          "1i the picker closes once the launch is under way")


def check_1j_master_launches_instantly(run: Run) -> None:
    master = run.master
    if master is None:
        print("skip 1j (no --master-base given)")
        return
    mctx, mpage = run.master_page()
    if master.hover_name and wait_for(mpage, lambda: row(mpage, master.hover_name).count() > 0, 20000):
        mbefore = len(sessions_under(master.api, master.path))
        mkebab = mpage.locator(
            f'.session-sidebar-group__headerrow:has-text("{master.project}") [data-project-menu]').first
        click_scrolled(mpage, mkebab)
        mpage.locator('#item-menu-host [role^="menuitem"]').first.click()
        got_session = wait_for(mpage, lambda: len(sessions_under(master.api, master.path)) > mbefore, 10000)
        run.tally.check(got_session,
                        "1j NEGATIVE CONTROL: on an UNMODIFIED slot, the SAME single click launches a session "
                        "immediately with no second click, proving 1c/1h can fail")
    else:
        print("skip 1j (the unmodified slot never drew the seeded row)")
    mctx.close()


def check_2_row_kebab_wording(run: Run) -> None:
    page, check, name = run.page, run.tally.check, run.seeds.names["s2"]["name"]
    open_row_kebab(page, name)
    panel = page.locator("#session-row-menu-panel")
    check(wait_for(page, lambda: panel.count() > 0, 4000), "2a the kebab panel opens")
    label_texts = [t.strip().lower() for t in panel.locator(".session-row-menu__label").all_inner_texts()]
    for want in ("fork agent", "new agent", "sleep agent", "kill agent"):
        check(want in label_texts, f'2b the panel offers "{want}"')
    check(not any("session" in t for t in label_texts), "2c no rendered label says the bare word session")
    raw_html = row(page, name).evaluate("(el) => el.outerHTML")
    check("session" in raw_html.lower(),
          "2d NEGATIVE CONTROL: the raw row markup still says session (in an attribute), proving 2c can fail")
    page.keyboard.press("Escape")


def check_3_tab_shape(run: Run) -> None:
    check = run.tally.check
    tab = run.page.locator('.session-sidebar-tabs [data-tab="agents"]')
    radius = tab.evaluate("(el) => getComputedStyle(el).borderRadius")
    check(radius == "0px", f"3a the agents tab is flat like the app's default tab (border-radius={radius!r})")
    if run.master is None:
        print("skip 3b (no --master-base given)")
        return
    mctx, mpage = run.master_page()
    mtab = mpage.locator('.session-sidebar-tabs [data-tab="agents"]')
    wait_for(mpage, lambda: mtab.count() > 0, 15000)
    mradius = mtab.evaluate("(el) => getComputedStyle(el).borderRadius") if mtab.count() else None
    check(bool(mradius) and mradius != "0px",
          f"3b NEGATIVE CONTROL: the SAME check on an unmodified slot is rounded (border-radius={mradius!r}), proving 3a can fail")
    mctx.close()


def check_5neg_master_hover_opens_nothing(run: Run) -> None:
    master = run.master
    if master is None or not master.hover_name:
        print("skip 5-neg (no --master-base given, or it could not be seeded there)")
        return
    mctx, mpage = run.master_page(track_errors=True)
    if wait_for(mpage, lambda: row(mpage, master.hover_name).count() > 0, 20000):
        open_row_kebab(mpage, master.hover_name)
        mpage.locator('#session-row-menu-panel [data-row-menu-item="add-to"]').hover()
        mpage.wait_for_timeout(600)
        run.shot(mpage, "master-hover-opens-nothing.png")
        run.tally.check(mpage.locator('#add-to-cascade-menu [data-node="group"]').count() == 0,
                        '5-neg NEGATIVE CONTROL: on an UNMODIFIED slot, hovering "add to" (no click) opens '
                        "nothing, proving 5a's hover-opens assertion below is real, not vacuously true")
    else:
        print("skip 5-neg (the unmodified slot never drew the seeded row)")
    mctx.close()


def check_4a_agent_add_to_group(run: Run) -> None:
    page, check, api, sd = run.page, run.tally.check, run.api, run.seeds
    s1 = sd.names["s1"]
    check(s1["uuid"] not in group_members(api, sd.group1),
          "4a-pre s1 does not start in group1 (this run's own negative control)")
    open_row_kebab(page, s1["name"])
    click_native_item(page, "add-to")
    click_cascade(page, "group", sd.group1)
    check(wait_for(page, lambda: s1["uuid"] in group_members(api, sd.group1)),
          "4a Agent kebab: Add to > Group adds the agent to the picked group")


def check_4b_agent_add_to_layout(run: Run) -> None:
    page, check, api, sd = run.page, run.tally.check, run.api, run.seeds
    s2 = sd.names["s2"]
    check(s2["uuid"] not in layout_members(api, sd.layout1),
          "4b-pre s2 does not start in layout1 (this run's own negative control)")
    open_row_kebab(page, s2["name"])
    click_native_item(page, "add-to")
    click_cascade(page, "layout", sd.layout1)
    check(wait_for(page, lambda: s2["uuid"] in layout_members(api, sd.layout1)),
          "4b Agent kebab: Add to > Layout adds the agent to the picked Layout")


def _open_group_add(page: Any, group_uuid: str) -> None:
    click_scrolled(page, page.locator(f'.session-sidebar-group[data-group="g:{group_uuid}"] [data-group-menu]').first)
    page.locator('#item-menu-host [role^="menuitem"]', has_text="add").first.click()


def check_4c_group_add_agents(run: Run) -> None:
    page, check, api, sd = run.page, run.tally.check, run.api, run.seeds
    s3 = sd.names["s3"]
    check(s3["uuid"] not in group_members(api, sd.group2),
          "4c-pre s3 does not start in group2 (this run's own negative control)")
    _open_group_add(page, sd.group2)
    click_cascade(page, "agents", s3["name"])
    check(wait_for(page, lambda: s3["uuid"] in group_members(api, sd.group2)),
          "4c Group kebab: Add > Agents adds the picked agent to the group")


def check_4d_group_add_layouts(run: Run) -> None:
    page, check, api, sd = run.page, run.tally.check, run.api, run.seeds
    s1 = sd.names["s1"]
    check(s1["uuid"] not in layout_members(api, sd.layout2),
          "4d-pre s1 does not start in layout2 (this run's own negative control)")
    _open_group_add(page, sd.group1)
    click_cascade(page, "layouts", sd.layout2)
    check(wait_for(page, lambda: s1["uuid"] in layout_members(api, sd.layout2)),
          "4d Group kebab: Add > Layouts adds every current member into the picked Layout")


def _open_layout_add(page: Any, layout_uuid: str) -> None:
    click_scrolled(page, page.locator(f'.session-sidebar-row[data-layout-uuid="{layout_uuid}"] [data-row-menu]').first)
    click_native_item(page, "add-to")


def check_4e_layout_add_agents(run: Run) -> None:
    page, check, api, sd = run.page, run.tally.check, run.api, run.seeds
    s10 = sd.names["s10"]
    check(s10["uuid"] not in layout_members(api, sd.layout2),
          "4e-pre s10 does not start in layout2 (this run's own negative control)")
    _open_layout_add(page, sd.layout2)
    click_cascade(page, "agents", s10["name"])
    check(wait_for(page, lambda: s10["uuid"] in layout_members(api, sd.layout2)),
          "4e Layout kebab: Add > Agents adds the picked agent to this Layout")


def check_4f_layout_add_groups(run: Run) -> None:
    page, check, api, sd = run.page, run.tally.check, run.api, run.seeds
    s7 = sd.names["s7"]
    check(s7["uuid"] not in layout_members(api, sd.layout1),
          "4f-pre s7 does not start in layout1 (this run's own negative control)")
    _open_layout_add(page, sd.layout1)
    click_cascade(page, "groups", sd.group3)
    check(wait_for(page, lambda: s7["uuid"] in layout_members(api, sd.layout1)),
          "4f Layout kebab: Add > Groups adds every member of the picked group into this Layout")


def check_5a_row_kebab_hover_flyout(run: Run) -> None:
    page, check, api, sd = run.page, run.tally.check, run.api, run.seeds
    s5 = sd.names["s5"]
    check(s5["uuid"] not in group_members(api, sd.group2),
          "5a-pre s5 does not start in group2 (this run's own negative control)")
    open_row_kebab(page, s5["name"])
    panel = page.locator("#session-row-menu-panel")
    panel.locator('[data-row-menu-item="add-to"]').hover()
    check(wait_for(page, lambda: page.locator('#add-to-cascade-menu [data-node="group"]').count() > 0, 4000),
          '5a hovering "add to" (no click) opens its nested submenu')
    check(panel.is_visible(), "5b the kebab panel stays open and visible while the nested submenu is open")
    run.shot(page, "row-kebab-hover-nested.png")
    page.locator('#add-to-cascade-menu [data-node="group"]').first.hover()
    check(wait_for(page, lambda: page.locator(f'#add-to-cascade-menu [data-node="{sd.group2}"]').count() > 0, 4000),
          "5c hovering the next level (Group) opens its own list of real group names")
    page.locator(f'#add-to-cascade-menu [data-node="{sd.group2}"]').first.click()
    check(wait_for(page, lambda: s5["uuid"] in group_members(api, sd.group2)),
          "5d a single click on the leaf performs the membership change")
    check(wait_for(page, lambda: panel.count() == 0, 4000), "5e picking the leaf also collapses the host kebab panel")


def check_5f_group_kebab_hover_flyout(run: Run) -> None:
    page, check, api, sd = run.page, run.tally.check, run.api, run.seeds
    s6 = sd.names["s6"]
    check(s6["uuid"] not in group_members(api, sd.group1),
          "5f-pre s6 does not start in group1 (this run's own negative control)")
    click_scrolled(page, page.locator(f'.session-sidebar-group[data-group="g:{sd.group1}"] [data-group-menu]').first)
    heading_menu = page.locator('#item-menu-host [role="menu"]').first
    heading_menu.locator('#item-menu-host [role^="menuitem"]', has_text="add").first.hover()
    check(wait_for(page, lambda: page.locator('#add-to-cascade-menu [data-node="agents"]').count() > 0, 4000),
          '5f hovering the group kebab\'s "add" (no click) opens its nested submenu')
    check(heading_menu.is_visible(), "5g the group heading menu stays open and visible while the nested submenu is open")
    run.shot(page, "group-kebab-hover-nested.png")
    page.locator('#add-to-cascade-menu [data-node="agents"]').first.hover()
    check(wait_for(page, lambda: page.locator(
              f'#add-to-cascade-menu [data-node="{s6["name"]}"]').count() > 0, 4000),
          "5h hovering the next level (Agents) opens its own list of real agent names")
    page.locator(f'#add-to-cascade-menu [data-node="{s6["name"]}"]').first.click()
    check(wait_for(page, lambda: s6["uuid"] in group_members(api, sd.group1)),
          "5i a single click on the leaf performs the membership change")
    check(wait_for(page, lambda: heading_menu.count() == 0, 4000), "5j picking the leaf also collapses the host group menu")


CHECKS_BEFORE_SHOT = (check_1_project_kebab_new_agent, check_1j_master_launches_instantly, check_2_row_kebab_wording,
                      check_3_tab_shape, check_5neg_master_hover_opens_nothing)
CHECKS_AFTER_SHOT = (check_4a_agent_add_to_group, check_4b_agent_add_to_layout, check_4c_group_add_agents,
                     check_4d_group_add_layouts, check_4e_layout_add_agents, check_4f_layout_add_groups,
                     check_5a_row_kebab_hover_flyout, check_5f_group_kebab_hover_flyout)


def _drive_browser(run: Run, sync_playwright: Any) -> bool:
    with sync_playwright() as pw:
        run.browser = pw.chromium.launch()
        ctx = run.browser.new_context(viewport=VIEWPORT, storage_state=run.args.storage_state)
        run.page = ctx.new_page()
        run.page.on("pageerror", lambda e: run.errors.append(str(e)))
        run.page.goto(run.args.base + "/", wait_until="domcontentloaded")
        if not wait_for(run.page, lambda: row(run.page, run.seeds.names["s1"]["name"]).count() > 0, 30000):
            print("CANNOT DETERMINE: the drawer never drew the seeded rows")
            return False
        run.page.wait_for_timeout(1000)
        for check_fn in CHECKS_BEFORE_SHOT:
            check_fn(run)
        run.shot(run.page, "sidebar-tabs.png")
        for check_fn in CHECKS_AFTER_SHOT:
            check_fn(run)
        run.tally.check(not run.errors, f"6 no page errors: {run.errors[:3]}")
        run.browser.close()
    return True
