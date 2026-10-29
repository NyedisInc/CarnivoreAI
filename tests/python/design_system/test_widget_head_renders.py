from __future__ import annotations

import socketserver
import threading

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so NOTHING about how the widget header "
        "renders was measured. This is a could-not-evaluate, not a pass."
    ),
)

from tests.helpers.focus_edge import assert_focus_edge, measure_focus_edge, settle_transitions  # noqa: E402
from tests.test_style_guide_themes import _free_port, _GuideHandler  # noqa: E402

HOST = "#sg-live-widget-head-sort"
HEAD = f"{HOST} .oc-frame-title"

_CLUSTER_JS = """(sel) => {
    const head = document.querySelector(sel);
    const drawn = (el) => el.getClientRects().length > 0 && el.getBoundingClientRect().width > 0;
    const out = [];
    let after = false;
    for (const el of head.children) {
        if (el.classList.contains('oc-frame-spacer')) { after = true; continue; }
        if (!after) continue;
        if (el.classList.contains('oc-head-group')) {
            if ([...el.children].some(drawn)) out.push('group');
        } else if (el.classList.contains('oc-head-sep')) {
            if (drawn(el)) out.push('sep');
        } else if (drawn(el)) {
            out.push('control');
        }
    }
    return out;
}"""


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), _GuideHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def page(base_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the widget header was NOT measured")
        context = chromium.new_context(viewport={"width": 1440, "height": 1000})
        guide = context.new_page()
        guide.goto(f"{base_url}/static/style-guide.html", wait_until="load")
        guide.wait_for_selector("html[data-sg-mounted='true']", state="attached", timeout=20000)
        guide.wait_for_selector(f"{HEAD} [data-head-close]", state="attached", timeout=20000)
        guide.evaluate("(sel) => document.querySelector(sel).closest('[inert]').removeAttribute('inert')", HOST)
        yield guide
        chromium.close()


def _cluster_at(page, width_px: int) -> list[str]:
    page.evaluate("([sel, w]) => { document.querySelector(sel).style.width = w + 'px'; }", [HOST, width_px])
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    return page.evaluate(_CLUSTER_JS, HEAD)


def test_a_sort_only_group_takes_its_separator_with_it_when_narrow(page) -> None:
    wide = _cluster_at(page, 800)
    assert wide == ["group", "sep", "control", "sep", "control"], wide
    narrow = _cluster_at(page, 420)
    assert narrow == ["control", "sep", "control"], narrow
    assert narrow[0] != "sep" and narrow[-1] != "sep", narrow


def test_the_close_x_turns_coral_only_under_the_pointer(page) -> None:
    close = f"{HEAD} [data-head-close]"
    coral = page.evaluate(
        """(sel) => {
            const probe = document.createElement('span');
            probe.style.color = 'var(--oc-coral)';
            document.querySelector(sel).appendChild(probe);
            const value = getComputedStyle(probe).color;
            probe.remove();
            return value;
        }""",
        HEAD,
    )
    page.mouse.move(0, 0)
    settle_transitions(page, close, timeout_ms=3000)
    rest = page.evaluate("(sel) => getComputedStyle(document.querySelector(sel)).color", close)
    page.hover(close)
    settle_transitions(page, close, timeout_ms=3000)
    hover = page.evaluate("(sel) => getComputedStyle(document.querySelector(sel)).color", close)
    assert rest != coral, (rest, coral)
    assert hover == coral, (hover, coral)


def test_the_menu_button_shows_keyboard_focus_on_its_own_border(page) -> None:
    measured = measure_focus_edge(page, f"{HEAD} .oc-frame-corner")
    assert measured["focus"]["edgeWidth"] == "1px", measured
    assert_focus_edge(measured, "widget header menu button")


PLACEMENT = "#sg-live-placement-head"

_THEMES = ("carnivore", "dracula")


@pytest.mark.parametrize("theme", _THEMES)
def test_a_drawer_card_wears_the_same_header_under_each_theme(base_url, theme: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the drawer card header was NOT measured")
        try:
            guide = chromium.new_context(viewport={"width": 1440, "height": 1000}).new_page()
            suffix = "" if theme == "carnivore" else f"?theme={theme}"
            guide.goto(f"{base_url}/static/style-guide.html{suffix}", wait_until="load")
            guide.wait_for_selector(f"html[data-sg-theme='{theme}']", state="attached", timeout=20000)
            head = f"{PLACEMENT} .oc-frame-title"
            guide.wait_for_selector(f"{head} [data-head-close]", state="attached", timeout=20000)
            settle_transitions(guide, f"{head} .oc-frame-name", timeout_ms=3000)
            measured = guide.evaluate(
                """(sel) => {
                    const head = document.querySelector(sel);
                    const probe = document.createElement('span');
                    probe.style.color = 'var(--oc-orange)';
                    head.appendChild(probe);
                    const accent = getComputedStyle(probe).color;
                    probe.remove();
                    return {
                        height: head.getBoundingClientRect().height,
                        first: head.firstElementChild.matches('.oc-frame-cornerwrap') && !!head.firstElementChild.querySelector('[data-corner]'),
                        accent,
                        name: getComputedStyle(head.querySelector('.oc-frame-name')).color,
                        icon: getComputedStyle(head.querySelector('[data-corner]')).color,
                    };
                }""",
                head,
            )
            cluster = guide.evaluate(_CLUSTER_JS, head)
        finally:
            chromium.close()
    assert measured["height"] == 31, measured
    assert measured["first"], measured
    assert measured["name"] == measured["accent"], measured
    assert measured["icon"] != measured["accent"], measured
    assert cluster == ["control"], cluster


def _placement_page(pw, base_url: str, width: int):
    try:
        chromium = pw.chromium.launch(args=["--use-mock-keychain"])
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"chromium could not launch ({exc}); the drawer card header was NOT measured")
    guide = chromium.new_context(viewport={"width": width, "height": 1000}).new_page()
    guide.goto(f"{base_url}/static/style-guide.html", wait_until="load")
    guide.wait_for_selector("html[data-sg-mounted='true']", state="attached", timeout=20000)
    guide.wait_for_selector(f"{PLACEMENT} .oc-frame-title [data-head-close]", state="attached", timeout=20000)
    guide.evaluate("(sel) => document.querySelector(sel).closest('[inert]').removeAttribute('inert')", PLACEMENT)
    return chromium, guide


def test_the_header_stays_31px_in_a_desktop_window_under_1024(base_url) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        chromium, guide = _placement_page(pw, base_url, 900)
        try:
            heights = guide.evaluate(
                """(sel) => ({
                    head: document.querySelector(sel + ' .oc-frame-title').getBoundingClientRect().height,
                    corner: document.querySelector(sel + ' [data-corner]').getBoundingClientRect().height,
                })""",
                PLACEMENT,
            )
        finally:
            chromium.close()
    assert heights == {"head": 31, "corner": 20}, heights


@pytest.mark.parametrize("width", [192, 240, 256])
def test_a_narrow_card_keeps_its_close_x_inside_the_head(base_url, width: int) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        chromium, guide = _placement_page(pw, base_url, 1440)
        try:
            guide.evaluate("([sel, w]) => { document.querySelector(sel + ' .sg-drawer-host').style.width = w + 'px'; }", [PLACEMENT, width])
            guide.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
            measured = guide.evaluate(
                """(sel) => {
                    const head = document.querySelector(sel + ' .oc-frame-title');
                    const close = head.querySelector('[data-head-close]').getBoundingClientRect();
                    return {
                        width: head.getBoundingClientRect().width,
                        scroll: head.scrollWidth,
                        client: head.clientWidth,
                        closeRight: close.right,
                        headRight: head.getBoundingClientRect().right,
                        gap: getComputedStyle(head).columnGap,
                    };
                }""",
                PLACEMENT,
            )
        finally:
            chromium.close()
    assert measured["width"] == width, measured
    assert measured["scroll"] <= measured["client"], measured
    assert measured["closeRight"] <= measured["headRight"], measured
    assert measured["gap"] == "4px", measured


def test_a_pressed_toggle_in_the_head_is_not_the_accent(base_url) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        chromium, guide = _placement_page(pw, base_url, 1440)
        try:
            measured = guide.evaluate(
                """(sel) => {
                    const head = document.querySelector(sel + ' .oc-frame-title');
                    const probe = document.createElement('span');
                    probe.style.color = 'var(--oc-orange)';
                    head.appendChild(probe);
                    const accent = getComputedStyle(probe).color;
                    probe.remove();
                    // The head no longer carries a toggle of its own (the gear is a menu item now), so the pressed bare
                    // toggle is placed here: the rule under test is `[data-widget-head] .oc-ibtn--bare[aria-pressed]`.
                    const gear = document.createElement('button');
                    gear.type = 'button';
                    gear.className = 'oc-ibtn oc-ibtn--bare';
                    gear.textContent = 'x';
                    gear.setAttribute('aria-pressed', 'true');
                    head.appendChild(gear);
                    const outside = gear.cloneNode(true);
                    head.closest('.sg-drawer-host').parentElement.appendChild(outside);
                    const accented = [...head.querySelectorAll('*')]
                        .filter((el) => !el.closest('.oc-frame-name') && getComputedStyle(el).color === accent)
                        .map((el) => el.className.baseVal ?? el.className);
                    const result = { accent, accented, outside: getComputedStyle(outside).color };
                    outside.remove();
                    return result;
                }""",
                PLACEMENT,
            )
        finally:
            chromium.close()
    assert measured["accented"] == [], measured
    assert measured["outside"] == measured["accent"], measured
