
from __future__ import annotations

import asyncio
import base64
import os
import signal
import sqlite3
import subprocess
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.config.browser import BrowserConfig
from src.core import resource_push
from src.core.browsers import store
from src.core.resource_push.topics import BROWSERS as BROWSERS_TOPIC
from src.core.browsers.input import map_input
from src.core.browsers.stream import Viewer
from src.core.browsers.url_policy import (
    ABOUT_BLANK,
    error_code,
    is_allowed,
    normalize_url,
    origin_of,
    storable_url,
)

logger = structlog.get_logger()

CHROME_APP = Path("/Applications/Google Chrome.app")

NO_CHROMIUM = (
    "no chromium found: install google chrome, or run "
    "venv/bin/python3 -m playwright install chromium-headless-shell"
)

MAX_VIEWERS = 8

CLOSE_TIMEOUT_S = 5.0

MIN_SIDE, MAX_WIDTH, MAX_HEIGHT, MAX_DPR = 200, 3840, 2160, 2.0

JPEG_QUALITY = 70

IGNORED_DEFAULT_ARGS = [
    "--disable-popup-blocking",
    "--disable-client-side-phishing-detection",
]

EXTRA_ARGS = ["--block-new-web-contents"]


class BrowserUnavailable(RuntimeError):
    pass


class CapReached(RuntimeError):
    pass




def _processes() -> List[Tuple[int, str]]:
    out = subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True,
        check=True, timeout=10,
    ).stdout
    rows = []
    for line in out.splitlines():
        head, _, command = line.strip().partition(" ")
        if head.isdigit() and int(head) != os.getpid():
            rows.append((int(head), command))
    return rows


def _processes_matching(needle: str) -> List[int]:
    return [pid for pid, command in _processes() if needle in command]


def profile_processes(profile: Path) -> List[int]:
    return _processes_matching(f"--user-data-dir={profile}")


def _kill(pids: List[int]) -> int:
    delivered = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
            delivered += 1
        except (ProcessLookupError, PermissionError):
            pass
    return delivered


def sweep_orphans(state_dir: Path, known_ids: Optional[Set[str]],
                  live_ids: Set[str] = frozenset()) -> Dict[str, int]:
    root = store.browsers_root(state_dir)
    spared = [f"--user-data-dir={store.profile_dir(state_dir, i)}" for i in live_ids]
    killed = _kill([
        pid for pid, command in _processes()
        if f"--user-data-dir={root}/" in command
        and not any(needle in command for needle in spared)
    ])
    removed = 0
    if known_ids is not None and root.is_dir():
        for folder in root.iterdir():
            if store.is_valid_id(folder.name) and folder.name not in known_ids:
                store.delete_profile(state_dir, folder.name)
                removed += 1
    return {"killed": killed, "folders_removed": removed}




@dataclass
class Viewport:

    width: int = 1280
    height: int = 800
    dpr: float = 1.0


class LiveBrowser:

    def __init__(self, browser_id: str, profile: Path, context: Any, page: Any, cdp: Any,
                 on_url: Callable[[str, str], None],
                 on_gone: Callable[[str, str], None]) -> None:
        self.id, self.profile = browser_id, profile
        self.context, self.page, self.cdp = context, page, cdp
        self.viewers: Set[Viewer] = set()
        self.viewport = Viewport()
        self.idle_task: Optional[asyncio.Task] = None
        self._on_url, self._on_gone = on_url, on_gone
        self._dialog: Any = None
        self._casting = False
        self._tasks: Set[asyncio.Task] = set()
        self.stopping = False


    async def attach(self) -> None:
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.cdp.on("Page.windowOpen", self._on_window_open)
        self.page.on("framenavigated", self._on_navigated)
        self.page.on("load", lambda _page: self._spawn(self._send_nav(loading=False)))
        self.page.on("dialog", self._on_dialog)
        self.page.on("download", lambda _d: self.broadcast_notice(
            "downloads are not supported in a browser session"))
        self.page.on("filechooser", lambda _f: self.broadcast_notice(
            "file uploads are not supported in a browser session"))
        self.page.on("crash", lambda _p: self._on_gone(self.id, "crashed"))
        self.context.on("page", self._on_popup)
        self.context.on("close", lambda _c: self._on_gone(self.id, "exited"))
        await self.cdp.send("Page.enable")
        await self._apply_viewport()

    def _spawn(self, coro: Any) -> None:
        if self.stopping:
            coro.close()
            return
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("browser_task_failed", browser_id=self.id,
                           error=type(task.exception()).__name__)


    def broadcast(self, message: Dict[str, Any]) -> None:
        for viewer in list(self.viewers):
            viewer.offer_text(message)

    def broadcast_notice(self, message: str) -> None:
        self.broadcast({"type": "notice", "message": message})

    def meta(self) -> Dict[str, Any]:
        v = self.viewport
        return {"type": "meta", "width": v.width, "height": v.height, "dpr": v.dpr}

    async def nav_message(self, loading: bool) -> Dict[str, Any]:
        index, last, title = 0, 0, ""
        try:
            history = await self.cdp.send("Page.getNavigationHistory")
            index, last = history["currentIndex"], len(history["entries"]) - 1
            title = await self.page.title()
        except driver_errors():
            pass
        return {
            "type": "nav", "url": self.page.url, "title": title,
            "canGoBack": index > 0, "canGoForward": index < last,
            "loading": loading,
        }

    async def _send_nav(self, loading: bool) -> None:
        self.broadcast(await self.nav_message(loading))

    def _on_frame(self, params: Dict[str, Any]) -> None:
        jpeg = base64.b64decode(params["data"])
        for viewer in list(self.viewers):
            viewer.offer_frame(jpeg)
        self._spawn(self.cdp.send("Page.screencastFrameAck",
                                  {"sessionId": params["sessionId"]}))

    def _on_navigated(self, frame: Any) -> None:
        if frame is not self.page.main_frame:
            return
        self._on_url(self.id, frame.url)
        self._spawn(self._send_nav(loading=True))

    def _on_dialog(self, dialog: Any) -> None:
        if not self.viewers:
            self._spawn(dialog.dismiss())
            return
        self._dialog = dialog
        self.broadcast({"type": "dialog", "kind": dialog.type,
                        "message": dialog.message[:2000],
                        "defaultPrompt": dialog.default_value[:2000]})

    def _on_window_open(self, params: Dict[str, Any]) -> None:
        if not params.get("userGesture"):
            return
        url = params.get("url", "")
        if url != ABOUT_BLANK and is_allowed(url):
            self._spawn(self.cdp.send("Page.navigate", {"url": url}))
        else:
            self.broadcast_notice("a popup was closed: browser sessions have one tab")

    def _on_popup(self, popup: Any) -> None:
        self._spawn(popup.close())


    async def _apply_viewport(self) -> None:
        v = self.viewport
        await self.cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": v.width, "height": v.height,
            "deviceScaleFactor": v.dpr, "mobile": False,
        })
        if self._casting:
            await self.cdp.send("Page.stopScreencast")
            await self._start_cast()

    async def _start_cast(self) -> None:
        v = self.viewport
        await self.cdp.send("Page.startScreencast", {
            "format": "jpeg", "quality": JPEG_QUALITY, "everyNthFrame": 1,
            "maxWidth": int(v.width * v.dpr), "maxHeight": int(v.height * v.dpr),
        })
        self._casting = True

    async def add_viewer(self, viewer: Viewer) -> bool:
        if len(self.viewers) >= MAX_VIEWERS:
            return False
        self.viewers.add(viewer)
        viewer.offer_text(self.meta())
        viewer.offer_text(await self.nav_message(loading=False))
        if not self._casting:
            await self._start_cast()
        try:
            shot = await self.cdp.send("Page.captureScreenshot",
                                       {"format": "jpeg", "quality": JPEG_QUALITY})
            viewer.offer_frame(base64.b64decode(shot["data"]))
        except driver_errors() as exc:
            logger.info("browser_first_paint_skipped", browser_id=self.id,
                        error=type(exc).__name__)
        return True

    async def remove_viewer(self, viewer: Viewer) -> None:
        self.viewers.discard(viewer)
        if not self.viewers and self._casting and not self.stopping:
            self._casting = False
            with suppress(*driver_errors()):
                await self.cdp.send("Page.stopScreencast")


    async def navigate(self, url: str) -> None:
        logger.info("browser_navigate", browser_id=self.id, origin=origin_of(url))
        await self.cdp.send("Page.navigate", {"url": url})

    async def handle(self, msg: Dict[str, Any], *, may_resize: bool) -> None:
        kind = msg.get("type")
        if kind in ("mouse", "key", "text"):
            method, params = map_input(msg, self.viewport.width, self.viewport.height)
            await self.cdp.send(method, params)
        elif kind == "navigate":
            url = msg.get("url")
            await self.navigate(normalize_url(url if isinstance(url, str) else None))
        elif kind in ("back", "forward"):
            history = await self.cdp.send("Page.getNavigationHistory")
            target = history["currentIndex"] + (-1 if kind == "back" else 1)
            if 0 <= target < len(history["entries"]):
                await self.cdp.send("Page.navigateToHistoryEntry",
                                    {"entryId": history["entries"][target]["id"]})
        elif kind == "reload":
            await self.cdp.send("Page.reload")
        elif kind == "stop":
            await self.cdp.send("Page.stopLoading")
        elif kind == "resize" and may_resize:
            await self._resize(msg)
        elif kind == "dialog" and self._dialog is not None:
            dialog, self._dialog = self._dialog, None
            prompt = msg.get("promptText")
            if msg.get("accept") is True:
                await dialog.accept(prompt[:2000] if isinstance(prompt, str) else "")
            else:
                await dialog.dismiss()

    async def _resize(self, msg: Dict[str, Any]) -> None:
        try:
            width = int(min(max(int(msg["width"]), MIN_SIDE), MAX_WIDTH))
            height = int(min(max(int(msg["height"]), MIN_SIDE), MAX_HEIGHT))
            dpr = float(min(max(float(msg.get("dpr", 1.0)), 0.5), MAX_DPR))
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        self.viewport = Viewport(width, height, dpr)
        await self._apply_viewport()
        self.broadcast(self.meta())

    async def close(self) -> None:
        self.stopping = True
        for task in list(self._tasks):
            task.cancel()
        try:
            await asyncio.wait_for(self.context.close(), CLOSE_TIMEOUT_S)
        except driver_errors() as exc:
            logger.warning("browser_close_timed_out", browser_id=self.id,
                           error=type(exc).__name__)
        try:
            await asyncio.to_thread(lambda: _kill(profile_processes(self.profile)))
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("browser_kill_scan_failed", browser_id=self.id,
                           error=type(exc).__name__)




class BrowserManager:

    def __init__(self, state_dir: Path, config: Callable[[], BrowserConfig]) -> None:
        self.state_dir = Path(state_dir)
        self._config = config
        self.live: Dict[str, LiveBrowser] = {}
        self._pw: Any = None
        self._lock = asyncio.Lock()
        self._writes: Set[asyncio.Task] = set()

    def is_live(self, browser_id: str) -> bool:
        return browser_id in self.live

    def viewer_count(self, browser_id: str) -> int:
        live = self.live.get(browser_id)
        return len(live.viewers) if live else 0

    async def _driver(self) -> Any:
        if self._pw is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise BrowserUnavailable(
                    "playwright is not installed: run venv/bin/pip install -r requirements.txt"
                ) from exc
            self._pw = await async_playwright().start()
        return self._pw

    def _binary(self, cfg: BrowserConfig) -> Dict[str, Any]:
        if cfg.executable:
            if not os.path.isfile(cfg.executable):
                raise BrowserUnavailable(
                    f"browser.executable in config.json does not exist: {cfg.executable}")
            return {"executable_path": cfg.executable}
        if CHROME_APP.is_dir():
            return {"channel": "chrome"}
        return {}

    async def ensure_live(self, browser_id: str, url: str) -> Tuple[LiveBrowser, bool]:
        async with self._lock:
            live = self.live.get(browser_id)
            if live is not None:
                return live, False
            live = await self._launch(browser_id, url)
        await self._open_url(live, url)
        return live, True

    async def launch(self, browser_id: str, url: str) -> LiveBrowser:
        async with self._lock:
            live = await self._launch(browser_id, url)
        await self._open_url(live, url)
        return live

    async def _launch(self, browser_id: str, url: str) -> LiveBrowser:
        cfg = self._config()
        if len(self.live) >= cfg.max_live:
            raise CapReached(
                f"{len(self.live)} browser sessions are already running and the "
                f"cap is {cfg.max_live}: close one, or raise browser.max_live in config.json")
        binary = self._binary(cfg)
        pw = await self._driver()
        profile = await asyncio.to_thread(store.make_profile_dir, self.state_dir, browser_id)
        from playwright.async_api import Error as PlaywrightError

        try:
            context = await pw.chromium.launch_persistent_context(
                str(profile), headless=True, chromium_sandbox=True,
                accept_downloads=False, no_viewport=True,
                ignore_default_args=IGNORED_DEFAULT_ARGS, args=EXTRA_ARGS, **binary,
            )
        except PlaywrightError as exc:
            logger.warning("browser_launch_failed", browser_id=browser_id,
                           error=error_code(exc))
            if "Executable doesn't exist" in str(exc):
                raise BrowserUnavailable(NO_CHROMIUM) from exc
            raise BrowserUnavailable("chromium failed to start; see the server log") from exc
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            cdp = await context.new_cdp_session(page)
            live = LiveBrowser(browser_id, profile, context, page, cdp,
                               self._remember_url, self._gone)
            await live.attach()
        except BaseException as exc:
            logger.warning("browser_attach_failed", browser_id=browser_id,
                           error=error_code(exc))
            with suppress(*driver_errors()):
                await asyncio.wait_for(context.close(), CLOSE_TIMEOUT_S)
            await asyncio.to_thread(lambda: _kill(profile_processes(profile)))
            if isinstance(exc, Exception):
                raise BrowserUnavailable("chromium started but could not be attached") from exc
            raise
        self.live[browser_id] = live
        self._arm_idle(live)
        resource_push.notify(BROWSERS_TOPIC)
        logger.info("browser_launched", browser_id=browser_id, origin=origin_of(url),
                    binary=next(iter(binary.values()), "headless-shell"))
        return live

    async def _open_url(self, live: LiveBrowser, url: str) -> None:
        if url == ABOUT_BLANK:
            return
        from playwright.async_api import Error as PlaywrightError
        try:
            await live.page.goto(url, wait_until="commit", timeout=15_000)
        except PlaywrightError as exc:
            logger.info("browser_open_url_failed", browser_id=live.id,
                        origin=origin_of(url), error=error_code(exc))

    def _remember_url(self, browser_id: str, url: str) -> None:
        if not is_allowed(url):
            return
        task = asyncio.ensure_future(asyncio.to_thread(
            _write_last_url, self.state_dir, browser_id, storable_url(url)))
        self._writes.add(task)
        task.add_done_callback(self._writes.discard)
        task.add_done_callback(lambda _t: resource_push.notify(BROWSERS_TOPIC))

    def _gone(self, browser_id: str, reason: str) -> None:
        live = self.live.get(browser_id)
        if live is None or live.stopping:
            return
        asyncio.ensure_future(self.stop(browser_id, reason))

    def _arm_idle(self, live: LiveBrowser) -> None:
        if live.idle_task is not None:
            live.idle_task.cancel()
        live.idle_task = None
        if live.viewers:
            return
        delay = self._config().idle_stop_minutes * 60

        async def _idle() -> None:
            await asyncio.sleep(delay)
            if not live.viewers:
                await self.stop(live.id, "idle")

        live.idle_task = asyncio.ensure_future(_idle())

    async def join(self, live: LiveBrowser, viewer: Viewer) -> bool:
        ok = await live.add_viewer(viewer)
        self._arm_idle(live)
        resource_push.notify(BROWSERS_TOPIC)
        return ok

    async def leave(self, live: LiveBrowser, viewer: Viewer) -> None:
        await live.remove_viewer(viewer)
        resource_push.notify(BROWSERS_TOPIC)
        if self.live.get(live.id) is live:
            self._arm_idle(live)

    async def stop(self, browser_id: str, reason: str) -> bool:
        async with self._lock:
            return await self._stop(browser_id, reason)

    async def _stop(self, browser_id: str, reason: str) -> bool:
        live = self.live.pop(browser_id, None)
        if live is None:
            return False
        if live.idle_task is not None and live.idle_task is not asyncio.current_task():
            live.idle_task.cancel()
        for viewer in list(live.viewers):
            viewer.offer_text({"type": "stopped", "reason": reason})
            viewer.close(1000, "browser stopped")
        await live.close()
        resource_push.notify(BROWSERS_TOPIC)
        logger.info("browser_stopped", browser_id=browser_id, reason=reason)
        return True

    async def discard(self, browser_id: str) -> None:
        async with self._lock:
            await self._stop(browser_id, "closed")
            await asyncio.to_thread(store.delete_profile, self.state_dir, browser_id)

    async def aclose(self) -> None:
        for browser_id in list(self.live):
            await self.stop(browser_id, "shutdown")
        if self._pw is not None:
            with suppress(*driver_errors()):
                await self._pw.stop()
            self._pw = None

    async def boot_sweep(self) -> None:
        try:
            known = await asyncio.to_thread(_stored_ids, self.state_dir)
        except _store_errors() as exc:
            logger.warning("browser_sweep_rows_unreadable", error=type(exc).__name__)
            known = None
        try:
            async with self._lock:
                owned = None if known is None else known | set(self.live)
                result = await asyncio.to_thread(
                    sweep_orphans, self.state_dir, owned, set(self.live))
            logger.info("browser_orphan_sweep", **result)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("browser_orphan_sweep_failed", error=type(exc).__name__)


def driver_errors() -> Tuple[type, ...]:
    try:
        from playwright.async_api import Error as PlaywrightError
    except ImportError:
        return (asyncio.TimeoutError, KeyError, TypeError, OSError)
    return (PlaywrightError, asyncio.TimeoutError, KeyError, TypeError, OSError)


def _store_errors() -> Tuple[type, ...]:
    from src.core.db import DatastoreUnreadableError

    return (sqlite3.Error, OSError, DatastoreUnreadableError)


def _stored_ids(state_dir: Path) -> Set[str]:
    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        return {row.id for row in store.list_all(conn)}


def _write_last_url(state_dir: Path, browser_id: str, url: str) -> None:
    from src.core.db import connect, db_path_for

    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            with conn:
                store.update(conn, browser_id, last_url=url)
    except _store_errors() as exc:
        logger.warning("browser_last_url_write_failed", browser_id=browser_id,
                       error=type(exc).__name__)
