
from __future__ import annotations

import json
import string
import time
from pathlib import Path
from typing import Optional

import pyotp
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

INSTRUMENT_JS = (Path(__file__).resolve().parent / "perf_instrument.js").read_text()

_ECHO_ALPHABET = string.ascii_lowercase + string.digits


def click_tolerant(page, selector: str, timeout_ms: int = 5000) -> None:
    try:
        page.wait_for_selector(selector, timeout=timeout_ms, state="visible")
    except PlaywrightTimeoutError:
        pass
    try:
        page.click(selector, timeout=timeout_ms, force=True)
    except PlaywrightTimeoutError:
        pass


def install_instrumentation(context) -> None:
    context.add_init_script(INSTRUMENT_JS)


def login_via_ui(page, base_url: str, totp_secret: str, timeout_ms: int = 30000) -> float:
    t0 = time.perf_counter()
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_selector("#totp-input", timeout=timeout_ms, state="visible")
    code = pyotp.TOTP(totp_secret).now()
    page.fill("#totp-input", code)
    click_tolerant(page, "#login-btn")
    page.wait_for_function(
        "() => { const b = window.__visibleBox && window.__visibleBox('#launchpad-screen.active'); return !!(b && b.visible); }",
        timeout=timeout_ms,
    )
    return (time.perf_counter() - t0) * 1000.0


def inject_authenticated_session(page, base_url: str, token: str, timeout_ms: int = 30000) -> None:
    page.context.add_init_script(
        "(() => { try { localStorage.setItem('claude_tunnel_token', "
        + json.dumps(token)
        + "); } catch (e) { /* storage blocked: the wait below reports it */ } })()"
    )
    page.goto(base_url, wait_until="domcontentloaded")
    page.wait_for_function(
        "() => { const b = window.__visibleBox && window.__visibleBox('#launchpad-screen.active'); return !!(b && b.visible); }",
        timeout=timeout_ms,
    )


def open_sidebar_control(page, timeout_ms: int = 5000) -> None:
    claw = page.locator('[data-rail="claw"]')
    if claw.count() and claw.is_visible():
        click_tolerant(page, '[data-rail="claw"]', timeout_ms=timeout_ms)
    else:
        click_tolerant(page, "#session-sidebar-toggle", timeout_ms=timeout_ms)


def ensure_sidebar_open(page, timeout_ms: int = 15000) -> None:
    sidebar_open = "#session-sidebar-panel.session-sidebar-panel--open"
    already_open = page.evaluate(
        f"() => {{ const b = window.__visibleBox('{sidebar_open}'); return !!(b && b.visible); }}"
    )
    if already_open:
        return
    open_sidebar_control(page, timeout_ms=min(timeout_ms, 5000))
    page.wait_for_function(
        f"() => {{ const b = window.__visibleBox('{sidebar_open}'); return !!(b && b.visible); }}",
        timeout=timeout_ms,
    )


def open_session_row(
    page, session_id: str, timeout_ms: int = 30000, scope: str = "", wait_for_paint: bool = True, marker: str = ""
) -> float:
    selector = f'{scope} [data-session-id="{session_id}"]'.strip()
    page.wait_for_selector(selector, timeout=timeout_ms, state="visible")
    page.evaluate(
        "(a) => window.__armSwitch(a.id, a.marker)",
        {"id": session_id, "marker": marker},
    )
    click_tolerant(page, selector)
    page.wait_for_function("() => !!window.__switchSnapshot()", polling=5, timeout=timeout_ms)
    snapshot = page.evaluate("() => window.__switchSnapshot()")
    return float(snapshot["doneAt"]) - float(snapshot["dispatchAt"])


def _ensure_render_hook(page, timeout_ms: int = 30000) -> None:
    page.wait_for_function(
        "() => !!(window.TerminalController && window.TerminalController.term)",
        timeout=timeout_ms,
    )
    ok = page.evaluate("() => window.__armRenderHook()")
    assert ok, "xterm Terminal instance did not accept the render hook"


def _arm_render_hook(page, timeout_ms: int = 30000) -> float:
    page.wait_for_function("() => !!window.__switchSnapshot()", polling=5, timeout=timeout_ms)
    return float(page.evaluate("() => window.__switchSnapshot().doneAt"))


def open_fresh_session_terminal(
    page, base_url: str, token: str, working_dir: str, label: str, timeout_ms: int = 30000
) -> tuple[dict, float]:
    t0 = page.evaluate("() => performance.now()")
    session = page.evaluate(
        """
        async ({ workingDir, label }) => {
            const resp = await fetch('/api/v1/sessions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + localStorage.getItem('claude_tunnel_token'),
                },
                body: JSON.stringify({
                    working_dir: workingDir,
                    auto_start_claude: true,
                    agent_type: 'shell',
                    label: label,
                }),
            });
            if (resp.status !== 201) {
                throw new Error('create refused: ' + resp.status + ' ' + (await resp.text()));
            }
            return await resp.json();
        }
        """,
        {"workingDir": working_dir, "label": label},
    )
    page.evaluate("(s) => window.__armSwitch(s.id, '')", session)
    page.evaluate("(s) => window.App.showTerminal(s)", session)
    page.wait_for_function(
        "() => { const b = window.__visibleBox && window.__visibleBox('#terminal-screen.active'); return !!(b && b.visible); }",
        timeout=timeout_ms,
    )
    t1 = _arm_render_hook(page, timeout_ms=timeout_ms)
    return session, float(t1) - float(t0)


def measure_typing_echo(page, count: int = 20, settle_ms: int = 3000) -> dict:
    dispatch_to_send: list[float] = []
    send_to_recv: list[float] = []
    recv_to_render: list[float] = []
    total: list[float] = []

    for i in range(count):
        ch = _ECHO_ALPHABET[i % len(_ECHO_ALPHABET)]
        t_arm = page.evaluate("() => window.__armEcho()")
        page.keyboard.press(ch)
        deadline = time.perf_counter() + (settle_ms / 1000.0)
        snap = None
        while time.perf_counter() < deadline:
            snap = page.evaluate("(needle) => window.__echoSnapshot(needle)", ch)
            if snap and snap.get("rendered"):
                break
            time.sleep(0.005)
        if not snap or not snap.get("rendered"):
            raise AssertionError(
                f"keystroke {ch!r} (#{i}) never rendered within {settle_ms}ms - "
                f"snapshot={snap}"
            )
        t_arm = snap.get("dispatchAt") or t_arm
        sent_at = snap.get("sentAt")
        recv_at = snap.get("recvAt")
        render_at = snap.get("renderAt")
        if sent_at is not None:
            dispatch_to_send.append(max(0.0, sent_at - t_arm))
        if sent_at is not None and recv_at is not None:
            send_to_recv.append(max(0.0, recv_at - sent_at))
        if recv_at is not None and render_at is not None:
            recv_to_render.append(max(0.0, render_at - recv_at))
        total.append(max(0.0, render_at - t_arm))
        page.keyboard.press("Backspace")
        time.sleep(0.02)

    return {
        "dispatch_to_send": dispatch_to_send,
        "send_to_recv": send_to_recv,
        "recv_to_render": recv_to_render,
        "total": total,
    }


def measure_visible_box(page, selector: str, action, settle_ms: int = 3000) -> Optional[float]:
    t0 = page.evaluate("() => performance.now()")
    action()
    deadline = time.perf_counter() + (settle_ms / 1000.0)
    while time.perf_counter() < deadline:
        box = page.evaluate("(sel) => window.__visibleBox(sel)", selector)
        if box and box.get("visible"):
            return float(box["t"]) - float(t0)
        time.sleep(0.004)
    return None


def measure_scroll_frame_times(page, container_selector: str, distance_px: int = 4000, steps: int = 40) -> list[float]:
    return page.evaluate(
        """
        async ({ sel, distance, steps }) => {
            const el = document.querySelector(sel);
            if (!el) return [];
            const gaps = [];
            let last = null;
            function frame(ts) {
                if (last !== null) gaps.push(ts - last);
                last = ts;
            }
            const perStep = Math.max(1, Math.floor(distance / steps));
            for (let i = 0; i < steps; i++) {
                el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + perStep);
                await new Promise((resolve) => requestAnimationFrame((ts) => { frame(ts); resolve(); }));
            }
            return gaps;
        }
        """,
        {"sel": container_selector, "distance": distance_px, "steps": steps},
    )
