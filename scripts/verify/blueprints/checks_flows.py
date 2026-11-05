
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from scripts.lib.verify_harness import dismiss_offers
from scripts.verify.blueprints.env import Env
from scripts.verify.blueprints.page_helpers import (
    SCREEN_SEL, click_text, close_any_modal, fill_session_zero, open_detail, open_drawer, opened_blueprints, row_for,
)


def _seed_two_shell_sessions(env: Env) -> list[int]:
    names = [f"vlA{env.tag}", f"vlB{env.tag}"]
    for name in names:
        made = env.server.call("POST", "/sessions", {"project_name": name, "working_dir": "~",
                                                      "agent_type": "shell", "auto_start_claude": False,
                                                      "copy_templates": False})
        if not isinstance(made, dict) or "tmux_session" not in made:
            raise RuntimeError(f"could not seed session {name}: {made!r}")
        env.made_tmux.append(made["tmux_session"])
    time.sleep(1.5)
    listing = env.server.listing()
    rows = []
    for name in names:
        row = next((r for tmux, r in listing.items() if tmux.endswith(name)), None)
        if not row:
            raise RuntimeError(f"no listing row for {name}")
        rows.append(row["session_row_id"])
    return rows


def _seed_layout_of(env: Env, rows: list[int]) -> str:
    share = 1 / len(rows)
    made_layout = env.server.call("POST", "/layouts", {
        "name": f"vl {env.tag}",
        "shape": {"layout": {"v": 6, "rows": [{"id": "r1", "kind": "flex", "size": 1,
                  "slots": [{"id": f"terminal:row:{rid}", "fr": share} for rid in rows]}],
                  "hidden": [], "heroCollapsed": False, "collapsed": []}, "groups": {}},
    })
    if not isinstance(made_layout, dict) or not made_layout.get("layout"):
        raise RuntimeError(f"could not seed the Layout: {made_layout!r}")
    uuid = made_layout["layout"]["layout_uuid"]
    env.made_layouts.append(uuid)
    env.layout_row_state["uuid"] = uuid
    return uuid


def _save_layout_via_kebab(env: Env, uuid: str) -> str:
    page = env.page
    row = page.locator(f'.session-sidebar-row[data-layout-uuid="{uuid}"][data-band="layouts"]')
    row.locator("[data-row-menu]").first.wait_for(state="visible", timeout=8000)
    row.locator("[data-row-menu]").first.click()
    save_item = page.locator('[data-row-menu-item="save-blueprint"]').first
    save_item.wait_for(state="visible", timeout=4000)
    save_item.click()
    name_field = page.locator("#text-prompt-input, .text-prompt-modal input[type=text]").first
    name_field.wait_for(state="visible", timeout=4000)
    bp_name = f"vlbp {env.tag}"
    name_field.fill(bp_name)
    page.locator('.text-prompt-modal button:has-text("save"), .modal-content button:has-text("save")').first.click()
    return bp_name


def check_save_as_blueprint(env: Env) -> None:
    args, page, report, server = env.args, env.page, env.report, env.server
    uuid = _seed_layout_of(env, _seed_two_shell_sessions(env))
    page.goto(args.base + f"/layout/{uuid}", wait_until="domcontentloaded")
    dismiss_offers(page)
    open_drawer(page)
    page.wait_for_timeout(800)
    report.check(page.locator(".oc-save-blueprint").count() == 0,
                 "12z. the floating save-as-blueprint corner control is gone")
    bp_name = _save_layout_via_kebab(env, uuid)
    page.wait_for_timeout(1500)
    listed = server.call("GET", "/blueprints")
    found = next((b for b in listed.get("blueprints", []) if b["name"] == bp_name), None)
    report.check(found is not None, "12b. the kebab's save-as-blueprint created a blueprint", json.dumps(listed)[:200])
    if found:
        env.made_blueprints.append(found["blueprint_uuid"])
        report.check(len(found["spec"]["sessions"]) == 2,
                     "12c. the saved blueprint carries both Layout members",
                     str(len(found["spec"]["sessions"])))


def check_load_blueprint_from_kebab(env: Env) -> None:
    args, page, report, server, tag, layout_row_state = env.args, env.page, env.report, env.server, env.tag, env.layout_row_state
    uuid = layout_row_state.get("uuid")
    seeded_name = f"vlbp {tag}"
    if not uuid:
        report.check(False, "12d. load-blueprint: no seeded Layout to test against")
        return
    if not any(b["name"] == seeded_name for b in server.call("GET", "/blueprints").get("blueprints", [])):
        report.check(False, "12d. load-blueprint: no saved blueprint to list")
        return
    page.goto(args.base + f"/layout/{uuid}", wait_until="domcontentloaded")
    dismiss_offers(page)
    open_drawer(page)
    page.wait_for_timeout(800)
    row = page.locator(f'.session-sidebar-row[data-layout-uuid="{uuid}"][data-band="layouts"]')
    row.locator("[data-row-menu]").first.wait_for(state="visible", timeout=8000)
    row.locator("[data-row-menu]").first.click()
    load_item = page.locator('[data-row-menu-item="load-blueprint"]').first
    item_present = load_item.count() > 0
    report.check(item_present, "12d. the Layout row's kebab offers load-blueprint")
    if not item_present:
        return
    load_item.click()
    picker = page.locator('.acm-menu[data-level="0"]')
    picker.wait_for(state="visible", timeout=4000)
    listed = seeded_name in picker.inner_text()
    report.check(listed, "12e. load-blueprint's picker lists the saved blueprint by name", picker.inner_text()[:200])
    view_all = page.locator('.acm-menu[data-level="0"] button:has-text("View all")')
    report.check(view_all.count() == 1, "12e2. the picker offers \"view all\"")
    if view_all.count() == 0:
        return
    view_all.first.click()
    page.locator(SCREEN_SEL).wait_for(state="visible", timeout=20000)
    preselected = page.locator(".bp-launch__member, #bp-name").count() > 0
    report.check(not preselected, "12f. nothing is preselected - the general list opened, not a launch/edit view")
    close_any_modal(page)


def check_editor_and_preview(env: Env) -> None:
    args, page, report, server, tag, repo, made_blueprints = env.args, env.page, env.report, env.server, env.tag, env.repo, env.made_blueprints
    opened_blueprints(page, args.base)
    click_text(page, page.locator(SCREEN_SEL), "new blueprint")
    page.locator("#bp-name").wait_for(state="visible", timeout=4000)
    bp_name = f"vlbp-edit {tag}"
    page.fill("#bp-name", bp_name)
    branch = f"feat/verify-{tag}"
    fill_session_zero(
        page, label="one", family="claude", mode="worktree",
        repo=str(repo), base_branch="master", branch=branch,
        skill="verify/nonexistent", prompt=f"verify editor prompt {tag}",
    )
    click_text(page, page.locator(".modal-content"), "save")
    row_for(page, bp_name).wait_for(state="visible", timeout=6000)
    listed = server.call("GET", "/blueprints")
    found = next((b for b in listed.get("blueprints", []) if b["name"] == bp_name), None)
    report.check(found is not None, "13a. the editor saved the worktree/skill/prompt blueprint")
    if not found:
        return
    made_blueprints.append(found["blueprint_uuid"])
    member = found["spec"]["sessions"][0]
    report.check(member["folder"]["mode"] == "worktree" and member["folder"]["branch"] == branch,
                 "13b. the stored spec carries the worktree folder", json.dumps(member["folder"]))
    report.check(member["skills"] == ["verify/nonexistent"], "13c. the stored spec carries the skill")
    report.check(member["opening_prompt"] == f"verify editor prompt {tag}",
                 "13d. the stored spec carries the opening prompt")
    click_text(page, row_for(page, bp_name), "launch")
    page.locator(".bp-launch__member").first.wait_for(state="visible", timeout=15000)
    body = page.locator(".bp-launch__list").inner_text()
    report.check(repo.name in body and branch in body,
                 "13e. the preview lists the worktree path and branch", body[:200])
    report.check("verify/nonexistent" in body, "13f. the preview lists the requested skill", body[:200])
    consent = page.locator(".bp-launch__consent input[type=checkbox]")
    if consent.count() > 0:
        report.check(not consent.first.is_checked(),
                     "13g. a script-consent tick is never pre-ticked")
    else:
        report.check(True, "13g. a script-consent tick is never pre-ticked (skill needs none here, "
                            "unknown to this install's catalog)")
    page.locator('.modal-content button:has-text("cancel")').first.click()
    page.wait_for_timeout(300)


def _blueprint_uuids(env: Env) -> set[str]:
    return {b["blueprint_uuid"] for b in env.server.call("GET", "/blueprints").get("blueprints", [])}


def _create_launch_blueprint(env: Env, branch: str) -> tuple[str, str]:
    page, tag = env.page, env.tag
    opened_blueprints(page, env.args.base)
    click_text(page, page.locator(SCREEN_SEL), "new blueprint")
    page.locator("#bp-name").wait_for(state="visible", timeout=4000)
    bp_name = f"vlbp-launch {tag}"
    page.fill("#bp-name", bp_name)
    fill_session_zero(page, label="worker", family="claude", mode="worktree",
                       repo=str(env.repo), base_branch="master", branch=branch,
                       prompt=f"verify launch prompt {tag}")
    click_text(page, page.locator(".modal-content"), "add session")
    page.fill("#bp-session-1-label", "shell")
    page.select_option("#bp-session-1-family", "shell")
    page.fill("#bp-session-1-path", str(env.existing_dir))
    click_text(page, page.locator(".modal-content"), "save")
    row_for(page, bp_name).wait_for(state="visible", timeout=6000)
    listed = env.server.call("GET", "/blueprints")
    found = next((b for b in listed.get("blueprints", []) if b["name"] == bp_name), None)
    if not found:
        raise RuntimeError(f"the launch blueprint was never saved: {listed!r}")
    env.made_blueprints.append(found["blueprint_uuid"])
    return bp_name, found["blueprint_uuid"]


def _launch_from_screen(env: Env, bp_name: str) -> None:
    page = env.page
    click_text(page, row_for(page, bp_name), "launch")
    page.locator(".bp-launch__member").first.wait_for(state="visible", timeout=15000)
    click_text(page, page.locator(".modal-content"), "launch")
    page.locator(".bp-launch__ok, .bp-launch__line--error").first.wait_for(state="visible", timeout=45000)


def _check_worktree(env: Env, branch: str) -> None:
    worktree_path = env.worktree_root / "app" / branch.replace("/", "-")
    on_disk = worktree_path.is_dir() and (worktree_path / ".git").exists()
    env.report.check(on_disk, "14a. the worktree exists on disk", str(worktree_path))
    if on_disk:
        current_branch = subprocess.run(
            ["git", "-C", str(worktree_path), "branch", "--show-current"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        env.report.check(current_branch == branch, "14b. the worktree is checked out on the requested branch",
                         current_branch)


def _check_worker_member(env: Env, listing: dict, uuid: str) -> None:
    report = env.report
    worker_row = next((r for tmux, r in listing.items() if tmux.endswith(f"blueprint-{uuid[:6]}") or
                        r.get("label") == "worker"), None)
    if worker_row is None:
        worker_row = next((r for r in listing.values() if r.get("label") == "worker"), None)
    report.check(worker_row is not None, "14c. the claude member's session row exists")
    if worker_row is None:
        return
    env.made_tmux.append(worker_row["tmux_session"])
    ps_out = subprocess.run(["ps", "-ax", "-o", "command"], capture_output=True, text=True,
                            timeout=5, check=False).stdout
    report.check(f"verify launch prompt {env.tag}" in ps_out,
                 "14d. the opening prompt reached the launched process' own command line")
    subprocess.run(["tmux", "-L", env.args.socket, "kill-session", "-t", "=" + worker_row["tmux_session"]],
                   capture_output=True, timeout=5, check=False)


def _check_open_layout_button(env: Env) -> None:
    page, report = env.page, env.report
    open_layout = page.locator('button:has-text("open layout")')
    if not open_layout.count():
        report.check(False, "14f. \"open layout\" navigates to the new Layout", "no such button rendered")
        return
    open_layout.first.click()
    page.wait_for_url("**/layout/*", timeout=8000)
    report.check("/layout/" in page.url, "14f. \"open layout\" navigates to the new Layout", page.url)
    env.made_layouts.append(page.url.rsplit("/layout/", 1)[-1])


def check_launch(env: Env) -> None:
    branch = f"feat/verify-launch-{env.tag}"
    bp_name, uuid = _create_launch_blueprint(env, branch)
    _launch_from_screen(env, bp_name)
    env.server.call("GET", "/blueprints")
    _check_worktree(env, branch)
    time.sleep(4)
    listing = env.server.listing()
    _check_worker_member(env, listing, uuid)
    shell_row = next((r for r in listing.values() if r.get("label") == "shell"), None)
    env.report.check(shell_row is not None, "14e. the shell member's session row exists")
    if shell_row is not None:
        env.made_tmux.append(shell_row["tmux_session"])
    _check_open_layout_button(env)


def _import_from_project(env: Env, folder: Path) -> None:
    page = env.page
    click_text(page, page.locator(SCREEN_SEL), "import from project")
    page.locator("#bp-import-project").wait_for(state="visible", timeout=4000)
    page.select_option("#bp-import-project", str(folder))
    click_text(page, page.locator(".modal-content"), "import from project")
    page.wait_for_timeout(1200)


def _cancel_dialog(env: Env) -> None:
    env.page.locator('.modal-content button:has-text("cancel")').first.click()
    env.page.wait_for_timeout(300)


def _check_export(env: Env, bp_name: str) -> None:
    page = env.page
    opened_blueprints(page, env.args.base)
    if row_for(page, bp_name).count() == 0:
        raise RuntimeError("the export source blueprint is not listed any more")
    open_detail(page, bp_name)
    click_text(page, page.locator(".mgr__detail"), "export")
    page.locator("#bp-export-project").wait_for(state="visible", timeout=4000)
    page.select_option("#bp-export-project", str(env.existing_dir))
    click_text(page, page.locator(".modal-content"), "export to project")
    page.wait_for_timeout(1200)
    swarm = env.existing_dir / ".carnivore" / "swarm.json"
    env.report.check(swarm.is_file(), "15a. export wrote .carnivore/swarm.json on disk", str(swarm))
    _cancel_dialog(env)
    source = next((b for b in env.server.call("GET", "/blueprints").get("blueprints", []) if b["name"] == bp_name), None)
    if source:
        env.server.call("DELETE", f"/blueprints/{source['blueprint_uuid']}")
        if source["blueprint_uuid"] in env.made_blueprints:
            env.made_blueprints.remove(source["blueprint_uuid"])


def _check_import_round_trip(env: Env) -> None:
    before = _blueprint_uuids(env)
    _import_from_project(env, env.existing_dir)
    new_ones = [b for b in env.server.call("GET", "/blueprints").get("blueprints", []) if b["blueprint_uuid"] not in before]
    env.report.check(len(new_ones) == 1, "15b. import created exactly one new blueprint", str(len(new_ones)))
    if new_ones:
        env.made_blueprints.append(new_ones[0]["blueprint_uuid"])
        env.report.check(len(new_ones[0]["spec"]["sessions"]) == 1,
                         "15c. the imported blueprint round-trips the session count")


def _check_name_clash(env: Env, bp_name: str) -> None:
    page, report = env.page, env.report
    opened_blueprints(page, env.args.base)
    _import_from_project(env, env.existing_dir)
    report.check("already exists" in page.locator(".bp-modal__error").inner_text(),
                 "D6. a name clash on import shows the real \"already exists\" sentence")
    rename_field = page.locator("#bp-import-name")
    report.check(rename_field.count() == 1 and rename_field.is_visible(),
                 "D6. the dialog stays open with the name field to rename into")
    renamed = f"{bp_name} renamed {env.tag}"
    rename_field.fill(renamed)
    before_rename = _blueprint_uuids(env)
    click_text(page, page.locator(".modal-content"), "import from project")
    page.wait_for_timeout(1200)
    renamed_new = [b for b in env.server.call("GET", "/blueprints").get("blueprints", [])
                   if b["blueprint_uuid"] not in before_rename]
    report.check(len(renamed_new) == 1 and renamed_new[0]["name"] == renamed,
                 "D6. resubmitting under the typed name succeeds", str(renamed_new))
    if renamed_new:
        env.made_blueprints.append(renamed_new[0]["blueprint_uuid"])


def _check_refused_import(env: Env, folder: Path, count_label: str, error_label: str) -> None:
    before = _blueprint_uuids(env)
    opened_blueprints(env.page, env.args.base)
    _import_from_project(env, folder)
    after = env.server.call("GET", "/blueprints").get("blueprints", [])
    env.report.check(len(after) == len(before), count_label, str(len(after) - len(before)))
    env.report.check(env.page.locator(".bp-modal__error").count() > 0, error_label)


def check_export_import(env: Env) -> None:
    bp_name = f"vlbp-edit {env.tag}"
    _check_export(env, bp_name)
    _check_import_round_trip(env)
    _check_name_clash(env, bp_name)
    _check_refused_import(env, env.no_swarm_dir, "15d. importing a project with no swarm.json creates nothing",
                          "15e. importing a project with no swarm.json shows a refusal")
    _cancel_dialog(env)
    malformed_dir = env.scratch / "malformed"
    (malformed_dir / ".carnivore").mkdir(parents=True)
    (malformed_dir / ".carnivore" / "swarm.json").write_text("{not json")
    added = env.server.call("POST", "/projects", {"name": f"verify-bp-malformed-{env.tag}", "path": str(malformed_dir)})
    if isinstance(added, dict):
        env.made_projects.append(f"verify-bp-malformed-{env.tag}")
    _check_refused_import(env, malformed_dir, "15f. a malformed swarm.json creates no blueprint",
                          "15g. a malformed swarm.json is refused with a visible error")


def check_solo_launch_done_open_session(env: Env) -> None:
    args, page, report, server, tag, existing_dir, made_blueprints, made_tmux = env.args, env.page, env.report, env.server, env.tag, env.existing_dir, env.made_blueprints, env.made_tmux
    opened_blueprints(page, args.base)
    click_text(page, page.locator(SCREEN_SEL), "new blueprint")
    page.locator("#bp-name").wait_for(state="visible", timeout=4000)
    bp_name = f"vlbp-solo {tag}"
    page.fill("#bp-name", bp_name)
    fill_session_zero(page, label="solo", family="shell", mode="existing", path=str(existing_dir))
    click_text(page, page.locator(".modal-content"), "save")
    row_for(page, bp_name).wait_for(state="visible", timeout=6000)
    listed = server.call("GET", "/blueprints")
    found = next((b for b in listed.get("blueprints", []) if b["name"] == bp_name), None)
    if not found:
        raise RuntimeError(f"the solo launch blueprint was never saved: {listed!r}")
    made_blueprints.append(found["blueprint_uuid"])
    click_text(page, row_for(page, bp_name), "launch")
    page.locator(".bp-launch__member").first.wait_for(state="visible", timeout=15000)
    click_text(page, page.locator(".modal-content"), "launch")
    page.locator('.modal-footer button:has-text("done")').first.wait_for(state="visible", timeout=15000)
    buttons = [b.strip() for b in page.locator(".modal-footer button").all_inner_texts()]
    report.check("cancel" not in buttons, "D9. the finished solo launch never offers \"cancel\"", str(buttons))
    report.check("done" in buttons, "D9. the finished solo launch offers \"done\"", str(buttons))
    open_btn = page.locator('.modal-footer button:has-text("open")')
    report.check(open_btn.count() == 1, "D9. an \"open session\" button is offered", str(buttons))
    if open_btn.count() == 1:
        open_btn.first.click()
        page.wait_for_timeout(1500)
        report.check(page.locator(".modal-overlay:visible").count() == 0,
                     "D9. clicking \"open\" closes the launch dialog")
    listing = server.listing()
    for tmux, row in listing.items():
        if row.get("label") == "solo":
            made_tmux.append(tmux)
