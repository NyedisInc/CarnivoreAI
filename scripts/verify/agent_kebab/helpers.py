
from __future__ import annotations

from typing import TYPE_CHECKING

import time

from scripts.lib.testsrv_client import access_token, api as testsrv_api
from scripts.lib.verify_harness import CleanupLedger

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

WAIT_MS = 15000


class Api:

    def __init__(self, base: str, storage_state: str) -> None:
        self.base = base
        self.token = access_token(storage_state, base)
        self.ledger = CleanupLedger(lambda path: self.call(path, "DELETE"))

    def call(self, path: str, method: str = "GET", body: dict | None = None):
        return testsrv_api(self.base, self.token, "/api/v1" + path, body, method, timeout=30)


def wait_for(page: Page, predicate, timeout_ms: int = WAIT_MS) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if predicate():
            return True
        page.wait_for_timeout(250)
    return bool(predicate())


def seed_session(api: Api, project: str, path: str) -> dict:
    body = api.call("/sessions", "POST", {
        "project_name": project, "working_dir": path, "agent_type": "claude",
        "auto_start_claude": False, "copy_templates": False,
    })
    name = body.get("tmux_session")
    records = api.call("/sessions/records")
    rec = next(r for r in records if r.get("tmux_name") == name)
    return {"name": name, "uuid": rec["session_uuid"], "row_id": rec["id"]}


def seed_layout(api: Api, name: str, row_ids: list[int]) -> str:
    slots = [{"id": f"terminal:row:{rid}", "fr": round(1 / len(row_ids), 4)} for rid in row_ids]
    body = api.call("/layouts", "POST", {
        "name": name,
        "shape": {"layout": {"v": 6, "rows": [{"id": "r1", "kind": "flex", "size": 1, "slots": slots}],
                             "hidden": [], "heroCollapsed": False, "collapsed": []},
                  "groups": {}},
    })
    api.ledger.record(f"/layouts/{body['layout']['layout_uuid']}")
    return body["layout"]["layout_uuid"]


def seed_group(api: Api, name: str, member_names: list[str]) -> str:
    body = api.call("/session-groups", "POST", {"name": name})
    uuid = next(g["group_uuid"] for g in body["groups"] if g["name"] == name)
    api.ledger.record(f"/session-groups/{uuid}")
    for member in member_names:
        api.call("/session-groups/assign", "POST", {"tmux_name": member, "group_uuid": uuid})
    return uuid


def sessions_under(api: Api, working_dir: str) -> list[dict]:
    return [r for r in api.call("/sessions/records") if r.get("working_dir") == working_dir]


def group_members(api: Api, uuid: str) -> set[str]:
    body = api.call("/session-groups")
    group = next(g for g in body["groups"] if g["group_uuid"] == uuid)
    return set(group.get("member_session_uuids") or [])


def layout_members(api: Api, uuid: str) -> set[str]:
    body = api.call("/layouts")
    layout = next(layer for layer in body["layouts"] if layer["layout_uuid"] == uuid)
    return {m["session_uuid"] for m in layout["members"]}


def row(page: Page, name: str):
    return page.locator(f'.session-sidebar-row[data-name="{name}"]')


def click_scrolled(page: Page, locator: Locator) -> None:
    last_exc: Exception | None = None
    for _ in range(5):
        try:
            locator.scroll_into_view_if_needed(timeout=4000)
            page.wait_for_timeout(150)
            locator.click(timeout=4000)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            page.wait_for_timeout(300)
    raise last_exc  # type: ignore[misc]


def open_row_kebab(page: Page, name: str) -> None:
    click_scrolled(page, row(page, name).locator("[data-row-menu]"))


def click_native_item(page: Page, item_id: str) -> None:
    page.locator(f'#session-row-menu-panel [data-row-menu-item="{item_id}"]').click()


def choose_first_direct_provider(page: Page) -> bool:
    provider_list = page.locator("#provider-list")
    if not wait_for(page, lambda: provider_list.locator(".folder-picker-item").count() > 0, 6000):
        return False
    items = provider_list.locator(".folder-picker-item")
    for i in range(items.count()):
        row_item = items.nth(i)
        if row_item.locator(".provider-item-more").count() == 0:
            row_item.click()
            return True
    items.first.click()
    model_items = page.locator("#provider-list .folder-picker-item")
    if wait_for(page, lambda: model_items.count() > 0, 4000):
        model_items.first.click()
        return True
    return False


def click_cascade(page: Page, *node_ids: str) -> None:
    for node_id in node_ids:
        page.locator(f'#add-to-cascade-menu [data-node="{node_id}"]').first.click()
        page.wait_for_timeout(150)
