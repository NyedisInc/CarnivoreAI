#!/usr/bin/env python3

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_csp_static_server import (  # noqa: E402
    assert_collector_live,
    assert_policy_served,
    collector_init_script,
    serve,
    violations,
)

LEGACY = "--legacy" in sys.argv

SCREEN_CHROME_CSS = "css/screen-chrome.css"

ROOT = Path(__file__).resolve().parent.parent
HARNESS = "/tests/manual/login-chrome-harness.html"

AUTH_ONLY = [
    ("slash-commands-btn", "slash commands button"),
    ("header-menu-toggle", "top-right menu button (kebab)"),
    ("configEditorBtn", "file editor"),
    ("session-sidebar-toggle", "conversations toggle"),
]

AUTH_ONLY_IN_MENU = [
    ("logoutBtn", "logout"),
    ("settingsBtn", "settings"),
]

AUTH_ONLY_MOBILE = [
    ("dpad-float-btn", "d-pad"),
]

ALWAYS = [("appTitle", "app title")]

GLYPH_FLOOR_PCT = 10.0
GLYPH_INSET_PX = 7
GLYPH_TARGETS = [("header-menu-toggle", "top-right menu button (kebab)")]




def describe(m: dict) -> str:
    if not m.get("present"):
        return "ABSENT from the DOM"
    return "%.1fx%.1f display=%s visibility=%s opacity=%s" % (
        m["w"], m["h"], m["display"], m["visibility"], m["opacity"]
    )


def compare(auth: dict, launch: dict, spec: list, failures: list,
            where: str) -> None:
    for eid, label in spec:
        a = auth.get(eid, {})
        b = launch.get(eid, {})
        if not a.get("present"):
            failures.append(
                "CANNOT COMPARE %s (%s, %s): absent from the DOM on the "
                "auth screen, so nothing was measured" % (eid, label, where)
            )
            continue
        if a.get("visible"):
            failures.append(
                "LEAK: %s (%s, %s) is VISIBLE on the login screen - %s"
                % (eid, label, where, describe(a))
            )
        if not b.get("present"):
            failures.append("%s (%s, %s): absent once authenticated"
                            % (eid, label, where))
        elif not b.get("visible"):
            failures.append(
                "%s (%s, %s) is NOT visible once authenticated - %s. Hiding "
                "it on the login screen must not hide it everywhere."
                % (eid, label, where, describe(b))
            )


def check(auth: dict, launch: dict, launch_menu: dict,
          m_auth: dict, m_launch: dict, failures: list) -> None:
    if auth.get("isAuthenticated") is not False:
        failures.append("auth screen: body.is-authenticated should be absent")
    if launch.get("isAuthenticated") is not True:
        failures.append("launchpad: body.is-authenticated should be present")

    compare(auth, launch, AUTH_ONLY, failures, "desktop")
    compare(auth, launch_menu, AUTH_ONLY_IN_MENU, failures, "overflow menu")
    compare(m_auth, m_launch, AUTH_ONLY_MOBILE, failures, "mobile 390px")

    for eid, label in ALWAYS:
        for name, bundle in (("auth", auth), ("launchpad", launch)):
            m = bundle.get(eid, {})
            if not m.get("visible"):
                failures.append(
                    "%s (%s) must stay visible on %s - %s"
                    % (eid, label, name, describe(m))
                )


def interior_ink_pct(png: bytes, inset: int = GLYPH_INSET_PX):
    from collections import Counter

    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = im.size
    if w <= 2 * inset or h <= 2 * inset:
        return None
    im = im.crop((inset, inset, w - inset, h - inset))
    px = list(im.getdata())
    if not px:
        return None
    bg = Counter(px).most_common(1)[0][0]
    n = sum(1 for p in px
            if abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2]) > 40)
    return 100.0 * n / len(px)


def measure_glyphs(page, failures: list, unknown: list) -> None:
    for eid, label in GLYPH_TARGETS:
        el = page.query_selector("#" + eid)
        if el is None:
            unknown.append("GLYPH %s (%s): element absent, nothing measured"
                           % (eid, label))
            continue
        box = page.evaluate(
            "id => { const r = document.getElementById(id)"
            ".getBoundingClientRect(); return [r.width, r.height]; }", eid)
        if not box or box[0] < 1 or box[1] < 1:
            unknown.append("GLYPH %s (%s): zero-area box, nothing measured"
                           % (eid, label))
            continue
        try:
            live = interior_ink_pct(el.screenshot())
        except ImportError:
            unknown.append("GLYPH %s (%s): Pillow not importable, ink could "
                           "not be measured" % (eid, label))
            continue
        if live is None:
            unknown.append("GLYPH %s (%s): interior too small to crop"
                           % (eid, label))
            continue

        saved = page.evaluate(
            "id => { const t = document.getElementById(id);"
            " const h = t.innerHTML; t.innerHTML = ''; return h; }", eid)
        try:
            blank = interior_ink_pct(el.screenshot())
        finally:
            page.evaluate(
                "([id, h]) => { document.getElementById(id).innerHTML = h; }",
                [eid, saved])
        if blank is None or blank >= GLYPH_FLOOR_PCT:
            unknown.append(
                "GLYPH %s (%s): positive control did not fall below the "
                "floor (blanked reads %s), so the live reading of %.1f%% "
                "proves nothing"
                % (eid, label, "None" if blank is None else "%.1f%%" % blank,
                   live))
            continue

        print("glyph ink     : %s = %.1f%% interior (floor %.1f%%, blanked "
              "control %.1f%%)" % (eid, live, GLYPH_FLOOR_PCT, blank))
        if live < GLYPH_FLOOR_PCT:
            failures.append(
                "EMPTY: %s (%s) paints only %.1f%% interior ink, below the "
                "%.1f%% floor - it renders as a bordered blank square"
                % (eid, label, live, GLYPH_FLOOR_PCT))


_INLINE_HANDLER_PROBE = """() => {
    const found = [];
    document.querySelectorAll('*').forEach(el => {
        for (const a of Array.from(el.attributes)) {
            if (!/^on[a-z]{2,24}$/i.test(a.name)) continue;
            const prop = a.name.toLowerCase();
            const compiled = typeof el[prop] === 'function';
            found.push({id: el.id || '', tag: el.tagName,
                        attr: a.name, value: a.value, compiled: compiled});
            try {
                el.dispatchEvent(new Event(prop.slice(2), {bubbles: false}));
            } catch (e) { /* dispatch is a witness, not the verdict */ }
        }
    });
    return found;
}"""

_PROBE_CONTROL = """() => {
    const el = document.createElement('button');
    el.id = '__csp_probe_control__';
    el.setAttribute('onclick', 'window.__cspProbeControlRan = true');
    document.body.appendChild(el);
    const compiled = typeof el.onclick === 'function';
    el.remove();
    return compiled;
}"""


def measure_inline_handlers(page, control_page, failures: list,
                            unknown: list) -> None:
    control = control_page.evaluate(_PROBE_CONTROL)
    if control is not False:
        unknown.append(
            "inline-handler probe: the synthetic control compiled its "
            "handler, so this page is NOT under `script-src 'self'` and a "
            "clean result here would prove nothing")
        return
    for h in page.evaluate(_INLINE_HANDLER_PROBE):
        failures.append(
            "DEAD INLINE HANDLER: <%s id=%r> carries %s=%r and the browser "
            "did NOT compile it under `script-src 'self'` - the control does "
            "nothing, throws nothing and rejects nothing. Wire it with "
            "addEventListener in its module."
            % (h["tag"].lower(), h["id"], h["attr"], h["value"]))


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("CANNOT DETERMINE: playwright is not importable", file=sys.stderr)
        return 2

    httpd, port = serve(ROOT)
    url = "http://127.0.0.1:%d%s" % (port, HARNESS)
    glyph_failures: list = []
    glyph_unknown: list = []
    csp_failures: list = []
    csp_unknown: list = []
    csp_proven: list = []

    def measure(page):
        page.evaluate("window.__setScreen('launchpad')")
        launch = page.evaluate("window.__chrome()")
        page.evaluate("window.__openMenu()")
        launch_menu = page.evaluate("window.__chrome()")
        page.evaluate("window.__setScreen('auth')")
        auth = page.evaluate("window.__chrome()")
        return launch, launch_menu, auth

    def open_page(browser, w, h):
        page = browser.new_page(viewport={"width": w, "height": h})
        page.add_init_script(collector_init_script())
        if LEGACY:
            page.add_init_script("window.__legacyShowAuth = true")
            page.route(
                "**/*" + SCREEN_CHROME_CSS,
                lambda route: route.fulfill(
                    status=200, content_type="text/css", body=""
                ),
            )
        response = page.goto(url)
        if page.evaluate("document.hidden"):
            return None
        if page.evaluate("window.innerWidth") != w:
            return None
        why = assert_policy_served(response) or assert_collector_live(page)
        if why is None:
            csp_proven.append(w)
        else:
            csp_unknown.append("%dpx viewport: %s" % (w, why))
        try:
            page.wait_for_function("() => window.__loginChromeReady === true",
                                   timeout=15000)
        except Exception:  # noqa: BLE001
            return None
        return page


    def collect_csp(page, w, failures: list) -> None:
        if w not in csp_proven:
            return
        for v in violations(page):
            failures.append(
                "CSP VIOLATION (%dpx): %s refused %s%s - under "
                "`script-src 'self'` the browser runs NOTHING here and "
                "reports no exception, so this control is dead on the real "
                "server no matter how it measures"
                % (w, v.get("directive") or "?", v.get("blocked") or "?",
                   (" near %r" % v["sample"]) if v.get("sample") else ""))

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            desktop = open_page(browser, 1280, 900)
            if desktop is None:
                print("CANNOT DETERMINE: desktop harness never became "
                      "measurable", file=sys.stderr)
                return 2
            launch, launch_menu, auth = measure(desktop)

            desktop.evaluate("window.__setScreen('launchpad')")
            measure_glyphs(desktop, glyph_failures, glyph_unknown)
            control_page = browser.new_page(viewport={"width": 800,
                                                       "height": 600})
            control_page.goto(url)
            measure_inline_handlers(desktop, control_page,
                                    csp_failures, csp_unknown)
            control_page.close()

            mobile = open_page(browser, 390, 844)
            if mobile is None:
                print("CANNOT DETERMINE: mobile harness never became "
                      "measurable", file=sys.stderr)
                return 2
            m_launch, _m_menu, m_auth = measure(mobile)
            collect_csp(desktop, 1280, csp_failures)
            collect_csp(mobile, 390, csp_failures)
            browser.close()
    finally:
        httpd.shutdown()

    failures: list = []
    check(auth, launch, launch_menu, m_auth, m_launch, failures)
    failures.extend(glyph_failures)
    failures.extend(csp_failures)

    every = AUTH_ONLY + AUTH_ONLY_IN_MENU
    print("login screen  :", ", ".join(
        "%s=%s" % (i, "VISIBLE" if auth.get(i, {}).get("visible") else "hidden")
        for i, _ in every))
    print("authenticated :", ", ".join(
        "%s=%s" % (i, "visible" if launch_menu.get(i, {}).get("visible")
                   else "HIDDEN")
        for i, _ in every))
    print("mobile 390px  :", ", ".join(
        "%s login=%s authed=%s" % (
            i,
            "VISIBLE" if m_auth.get(i, {}).get("visible") else "hidden",
            "visible" if m_launch.get(i, {}).get("visible") else "HIDDEN")
        for i, _ in AUTH_ONLY_MOBILE))

    if LEGACY:
        reproduced = [i for i, _ in AUTH_ONLY
                      if auth.get(i, {}).get("visible")]
        if reproduced:
            print("\nCONTROL OK: --legacy reproduced the reported bug; "
                  "these rendered on the login screen:")
            for i in reproduced:
                print("  -", i)
            return 0
        print("\nCONTROL BROKEN: --legacy reproduced NOTHING. It is "
              "supposed to restore the pre-fix state and show "
              "authenticated-only chrome on the login screen. A control "
              "that passes against fixed code cannot fail against broken "
              "code either, so it is not evidence of anything.",
              file=sys.stderr)
        return 1

    if failures:
        print("\nFAIL")
        for f in failures:
            print("  -", f)
        return 1
    if csp_proven:
        print("csp           : policy served and collector proven live at "
              + ", ".join("%dpx" % w for w in csp_proven)
              + "; %d violation(s)" % len(csp_failures))

    if glyph_unknown or csp_unknown:
        glyph_unknown = list(glyph_unknown) + list(csp_unknown)
    if glyph_unknown:
        print("\nCANNOT DETERMINE")
        for u in glyph_unknown:
            print("  -", u)
        return 2
    print("\nPASS: no authenticated-only chrome renders on the login screen,"
          "\n      and every header glyph measured paints real ink")
    return 0


if __name__ == "__main__":
    sys.exit(main())
