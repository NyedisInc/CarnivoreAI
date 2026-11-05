
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable, TypeVar

from perf_client import PerfClient, wait_until
from perf_env import PerfServer

T = TypeVar("T")

TOAST_COUNT_JS = "() => document.querySelectorAll('#toast-container .toast').length"
TOAST_VISIBLE_JS = "() => { const b = window.__visibleBox && window.__visibleBox('#toast-container .toast'); return !!(b && b.visible); }"
TOAST_DISMISS_JS = "() => document.querySelectorAll('#toast-container .toast button').forEach(b => b.click())"

SIDEBAR_SCOPE = "#session-sidebar-panel"
SIDEBAR_OPEN_SELECTOR = "#session-sidebar-panel.session-sidebar-panel--open"
COLD_LOGIN_ATTEMPTS = 3
PANEL_SETTLE_MS = 150
ROW_WAIT_MS = 15000
_ROW_IN_DOM_JS = "(sid) => !!document.querySelector('[data-session-id=\"' + sid + '\"]')"


@dataclass
class BaselineRun:

    result: dict
    quick: bool
    run_tag: str
    server: PerfServer
    client: PerfClient
    pb: ModuleType
    context: Any
    page: Any
    entry_session: dict = field(default_factory=dict)
    launch_session: dict = field(default_factory=dict)


def quick_reps(quick: bool, normal: int, quick_n: int) -> int:
    return quick_n if quick else normal


def safe_step(label: str, fn: Callable[[], T], default: T) -> T:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        print(f"measurement step {label!r} failed, continuing: {exc}", file=sys.stderr)
        return default


def _row_in_dom(page: Any, session_id: str) -> None:
    page.wait_for_function(_ROW_IN_DOM_JS, arg=session_id, timeout=ROW_WAIT_MS)


def phase_startup_cold(run: BaselineRun) -> None:
    last_login_error = None
    for attempt in range(COLD_LOGIN_ATTEMPTS):
        try:
            run.result["startup_cold_ms"] = run.pb.login_via_ui(
                run.page, run.server.base_url, run.server.totp_secret
            )
            last_login_error = None
            break
        except Exception as exc:  # noqa: BLE001
            last_login_error = exc
            print(f"cold login attempt {attempt + 1} failed: {exc}", file=sys.stderr)
    if last_login_error is not None:
        raise last_login_error


def phase_entry_session(run: BaselineRun) -> None:
    run.entry_session = run.client.create_session(run.server.work_dir, f"perf-entry-{run.run_tag}")
    wait_until(lambda: run.client.row_for(run.entry_session["id"]) is not None, timeout=15.0)
    _row_in_dom(run.page, run.entry_session["id"])


def phase_launch_cold(run: BaselineRun) -> None:
    run.launch_session, run.result["launch_cold_ms"] = run.pb.open_fresh_session_terminal(
        run.page, run.server.base_url, run.client.token, run.server.work_dir, f"perf-launch-cold-{run.run_tag}"
    )


def phase_typing(run: BaselineRun) -> None:
    run.result["typing_cold"] = run.pb.measure_typing_echo(run.page, count=quick_reps(run.quick, 5, 3))
    run.result["typing_warm"] = run.pb.measure_typing_echo(run.page, count=quick_reps(run.quick, 20, 4))


def phase_entry_cold(run: BaselineRun) -> None:
    entry_page = run.context.new_page()
    run.pb.inject_authenticated_session(entry_page, run.server.base_url, run.client.token)
    _row_in_dom(entry_page, run.entry_session["id"])
    run.result["entry_cold_ms"] = safe_step(
        "entry_cold", lambda: run.pb.open_session_row(entry_page, run.entry_session["id"]), None
    )
    entry_page.close()


def _open_row_via_sidebar(run: BaselineRun, session_id: str, wait_for_paint: bool) -> Any:
    run.pb.ensure_sidebar_open(run.page)
    return run.pb.open_session_row(run.page, session_id, scope=SIDEBAR_SCOPE, wait_for_paint=wait_for_paint)


def phase_switch(run: BaselineRun) -> None:
    entry_id, launch_id = run.entry_session["id"], run.launch_session["id"]
    run.pb.ensure_sidebar_open(run.page)
    run.result["session_entry_switch_target_ms"] = safe_step(
        "session_entry_switch_target",
        lambda: run.pb.open_session_row(run.page, entry_id, scope=SIDEBAR_SCOPE, wait_for_paint=False),
        None,
    )
    run.result["session_switch_cold_ms"] = safe_step(
        "session_switch_cold",
        lambda: run.pb.open_session_row(run.page, launch_id, scope=SIDEBAR_SCOPE, wait_for_paint=True),
        None,
    )
    safe_step("session_switch_warm_setup", lambda: _open_row_via_sidebar(run, entry_id, False), None)
    run.result["session_switch_warm_ms"] = safe_step(
        "session_switch_warm", lambda: _open_row_via_sidebar(run, launch_id, True), None
    )


def phase_launch_warm(run: BaselineRun) -> None:
    launched = safe_step(
        "launch_warm",
        lambda: run.pb.open_fresh_session_terminal(
            run.page, run.server.base_url, run.client.token, run.server.work_dir, f"perf-launch-warm-{run.run_tag}"
        ),
        (None, None),
    )
    run.result["launch_warm_ms"] = launched[1]


def phase_menu(run: BaselineRun) -> None:
    def open_menu() -> None:
        run.pb.open_sidebar_control(run.page)

    def measure(label: str) -> None:
        run.result[f"menu_open_{label}_ms"] = safe_step(
            f"menu_open_{label}",
            lambda: run.pb.measure_visible_box(run.page, SIDEBAR_OPEN_SELECTOR, open_menu),
            None,
        )

    measure("cold")
    run.page.keyboard.press("Escape")
    run.page.wait_for_timeout(PANEL_SETTLE_MS)
    measure("warm")
    run.page.keyboard.press("Escape")
    run.page.wait_for_timeout(PANEL_SETTLE_MS)


def _open_header_overflow(run: BaselineRun, attempts: int = 5) -> None:
    page = run.page
    for _ in range(attempts):
        if page.is_visible("#settingsBtn"):
            return
        run.pb.click_tolerant(page, "#header-menu-toggle")
        try:
            page.wait_for_selector("#settingsBtn", state="visible", timeout=1000)
            return
        except run.pb.PlaywrightTimeoutError:
            page.wait_for_timeout(PANEL_SETTLE_MS)


def _close_settings(run: BaselineRun) -> None:
    run.page.keyboard.press("Escape")
    try:
        run.page.wait_for_selector(".settings-page .st-main", state="hidden", timeout=3000)
    except run.pb.PlaywrightTimeoutError:
        pass


def phase_settings(run: BaselineRun) -> None:
    def open_settings() -> None:
        run.pb.click_tolerant(run.page, "#settingsBtn")

    for label in ("cold", "warm"):
        _open_header_overflow(run)
        run.result[f"settings_open_{label}_ms"] = safe_step(
            f"settings_open_{label}",
            lambda: run.pb.measure_visible_box(run.page, ".settings-page .st-main", open_settings),
            None,
        )
        _close_settings(run)
        run.page.wait_for_timeout(PANEL_SETTLE_MS)


def _wait_no_toast(page: Any, seconds: float) -> bool:
    deadline = time.perf_counter() + seconds
    while page.evaluate(TOAST_COUNT_JS) != 0 and time.perf_counter() < deadline:
        time.sleep(0.05)
    return page.evaluate(TOAST_COUNT_JS) == 0


def _one_toast_sample(run: BaselineRun, index: int) -> float | None:
    t0 = time.perf_counter()
    run.client.create_toast(run.launch_session["id"], "Notification", "perf check", f"toast-{index}")
    deadline = time.perf_counter() + 3.0
    while time.perf_counter() < deadline:
        if run.page.evaluate(TOAST_VISIBLE_JS):
            return (time.perf_counter() - t0) * 1000.0
        time.sleep(0.005)
    return None


def _run_notification_reps(run: BaselineRun) -> list:
    _open_row_via_sidebar(run, run.launch_session["id"], True)
    samples: list = []
    for i in range(quick_reps(run.quick, 8, 3)):
        if not _wait_no_toast(run.page, 2.0):
            continue
        sample = _one_toast_sample(run, i)
        if sample is not None:
            samples.append(sample)
        run.page.evaluate(TOAST_DISMISS_JS)
        time.sleep(0.1)
    return samples


def phase_notifications(run: BaselineRun) -> None:
    run.result["notification_toast"] = safe_step("notification_toast", lambda: _run_notification_reps(run), [])


def phase_scroll_proxy(run: BaselineRun) -> None:
    def scroll() -> list:
        list_page = run.context.new_page()
        try:
            run.pb.inject_authenticated_session(list_page, run.server.base_url, run.client.token)
            list_page.wait_for_timeout(300)
            return run.pb.measure_scroll_frame_times(list_page, "#launchpad-screen .launchpad-scroll")
        finally:
            list_page.close()

    run.result["scroll_frame_gaps_ms"] = safe_step("scroll_frame_gaps", scroll, [])


def phase_startup_warm(run: BaselineRun) -> None:
    def reload_timed() -> float:
        t0 = time.perf_counter()
        run.page.reload(wait_until="domcontentloaded")
        run.page.wait_for_function(
            "() => { const b = window.__visibleBox && window.__visibleBox('#launchpad-screen.active'); return !!(b && b.visible); }",
            timeout=15000,
        )
        return (time.perf_counter() - t0) * 1000.0

    run.result["startup_warm_ms"] = safe_step("startup_warm", reload_timed, None)


PHASES: tuple[Callable[[BaselineRun], None], ...] = (
    phase_startup_cold,
    phase_entry_session,
    phase_launch_cold,
    phase_typing,
    phase_entry_cold,
    phase_switch,
    phase_launch_warm,
    phase_menu,
    phase_settings,
    phase_notifications,
    phase_scroll_proxy,
    phase_startup_warm,
)


def run_browser_phases(run: BaselineRun) -> None:
    for phase in PHASES:
        phase(run)
