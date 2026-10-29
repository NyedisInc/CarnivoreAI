
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi.concurrency import run_in_threadpool

from src.config import settings
from src.core.layouts import store as layouts_store
from src.core.browser_pages import open_pages, page_tab
from src.core.browsers import store as browser_store
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.open_files import open_list
from src.cplugs.sdk import board_pages

logger = structlog.get_logger()


def _db_path() -> Path:
    return db_path_for(settings.get_state_dir())


class NoSuchItem(LookupError):

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Resolved:

    id: str
    title: str
    tmux_session: Optional[str] = None


async def _session(app: Any, item_id: str) -> Resolved:
    manager = getattr(app.state, "session_manager", None)
    info = await manager.get_session_info(item_id) if manager is not None else None
    if info is None:
        raise NoSuchItem("no live session has that id (sessions_list names them)")
    tmux = getattr(info, "tmux_session", None) or getattr(info.session, "tmux_session", None)
    return Resolved(info.session.id, getattr(info, "label", None) or tmux or info.session.id, tmux)


async def _file(app: Any, item_id: str) -> Resolved:
    row = open_list.get(item_id)
    if row is None:
        raise NoSuchItem("no open file row has that id (files_open opens one)")
    return Resolved(row.id, row.title)


async def _browser(app: Any, item_id: str) -> Resolved:
    page = open_pages.get(item_id)
    if page is not None:
        return Resolved(page.id, page.title)
    manager = getattr(app.state, "browser_manager", None)
    row = None
    if manager is not None:
        def read() -> Any:
            with closing(connect(db_path_for(manager.state_dir), create=False)) as conn:
                return browser_store.get(conn, item_id)
        try:
            row = await run_in_threadpool(read)
        except DatastoreUnreadableError as exc:
            logger.info("ui_show_browser_unreadable", error=str(exc))
    if row is None:
        raise NoSuchItem("no browser or page row has that id (browser_open opens one)")
    return Resolved(item_id, getattr(row, "label", None) or item_id)


async def _board(app: Any, slug: str) -> Resolved:
    port = board_pages.get()
    if port is None:
        raise NoSuchItem("the review board plugin is off, so no board page can be shown")
    try:
        key = page_tab.app_page(port.page_path(slug))["key"]
    except page_tab.AppPageRefused as exc:
        raise NoSuchItem(f"that board page cannot be shown: {exc}") from exc
    page = open_pages.get(open_pages.page_id(key))
    if page is None:
        raise NoSuchItem("that board is not open as a page row; task_manager_board_focus opens it")
    return Resolved(page.id, page.title)


async def _layout(app: Any, layout_uuid: str) -> Resolved:
    def read() -> Any:
        with closing(connect(_db_path(), create=False)) as conn:
            return layouts_store.get_layout(conn, layout_uuid)
    try:
        layout = await run_in_threadpool(read)
    except layouts_store.LayoutNotFound as exc:
        raise NoSuchItem("no saved layout has that uuid (dashboards and layouts are listed in the left bar)") from exc
    except (DatastoreUnreadableError, layouts_store.LayoutsUnavailable, OSError) as exc:
        logger.info("ui_show_layouts_unavailable", error=str(exc))
        raise NoSuchItem("the layouts could not be read") from exc
    return Resolved(layout.layout_uuid, layout.name)


async def _task_manager(app: Any, item_id: str) -> Resolved:
    return Resolved("", "task manager")


RESOLVERS = {"session": _session, "file": _file, "browser": _browser, "board": _board, "layout": _layout, "task_manager": _task_manager}


async def resolve(app: Any, kind: str, item_id: Optional[str]) -> Resolved:
    if kind == "task_manager":
        if item_id:
            raise NoSuchItem("task_manager takes no id")
        return await _task_manager(app, "")
    if not item_id:
        raise NoSuchItem(f"{kind} needs an id")
    return await RESOLVERS[kind](app, item_id)
