
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PAGE = REPO / "client" / "popout.html"
BOOT = REPO / "client" / "js" / "popout-boot.js"

FORBIDDEN = ("terminal", "xterm", "session-sidebar", "size-vote", "dist/app.js")


def _scripts() -> list[str]:
    return re.findall(r'<script[^>]*\ssrc="([^"]+)"', PAGE.read_text(encoding="utf-8"))


def test_page_loads_the_popout_bundle_and_the_event_feed() -> None:
    srcs = _scripts()
    assert "/static/dist/popout.js" in srcs, srcs
    assert "/static/js/app-events.js" in srcs, srcs
    assert "/static/js/socket-auth-recovery.js" in srcs, srcs
    assert srcs.index("/static/js/socket-auth-recovery.js") < srcs.index("/static/js/app-events.js"), srcs
    assert 'id="popout-screen"' in PAGE.read_text(encoding="utf-8")


def test_page_loads_no_terminal_drawer_or_size_vote_script() -> None:
    srcs = _scripts()
    assert srcs, "no script tags found: the scan looked at nothing"
    bad = [s for s in srcs for word in FORBIDDEN if word in s]
    assert not bad, bad


def test_page_has_no_inline_script() -> None:
    html = PAGE.read_text(encoding="utf-8")
    inline = re.findall(r"<script(?![^>]*\ssrc=)[^>]*>\s*\S", html)
    assert not inline, inline


def test_boot_script_opens_only_the_events_socket() -> None:
    text = BOOT.read_text(encoding="utf-8")
    assert "AppEvents.start" in text
    assert not re.search(r"pty_resize|/ws/terminal|TerminalController|openWebSocket", text)


def test_page_loads_the_shared_scrollbar_skin_after_styles() -> None:
    html = PAGE.read_text(encoding="utf-8")
    links = re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', html)
    assert links.count("/static/css/scrollbars.css") == 1, links
    assert links.index("/static/css/scrollbars.css") > links.index("/static/css/styles.css")
    skin = (REPO / "client" / "css" / "scrollbars.css").read_text(encoding="utf-8")
    assert "::-webkit-scrollbar" in skin, "the skin file carries no rules"


def test_page_loads_the_status_light_paint_in_order() -> None:
    html = PAGE.read_text(encoding="utf-8")
    links = re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', html)
    assert links.count("/static/css/status-dot.css") == 1, links
    assert links.count("/static/css/status-led.css") == 1, links
    assert links.index("/static/css/status-led.css") > links.index("/static/css/status-dot.css")
    paint = (REPO / "client" / "css" / "status-led.css").read_text(encoding="utf-8")
    assert "data-inner" in paint, "the LED stylesheet carries no rules"


def test_page_loads_the_shared_popup_look_last() -> None:
    html = PAGE.read_text(encoding="utf-8")
    sheets = re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', html)
    assert sheets[-1] == "/static/css/popup-focus.css"
    assert (REPO / "client" / "css" / "popup-focus.css").is_file()


def test_popout_paints_the_servers_global_theme_not_only_this_browsers_copy() -> None:
    srcs = _scripts()
    for name in ("preferences.js", "preference-bridge.js"):
        assert f"/static/js/{name}" in srcs, srcs
        assert srcs.index(f"/static/js/{name}") < srcs.index("/static/js/themes/registry.js"), srcs
    boot = BOOT.read_text(encoding="utf-8")
    assert "prefs.hydrate" in boot and boot.index("prefs.hydrate") < boot.index("themes.init()"), "hydrate must come first"
