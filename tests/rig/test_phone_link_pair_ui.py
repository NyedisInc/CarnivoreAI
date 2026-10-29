
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import struct
import time
from pathlib import Path

import httpx
import pytest

HOST = os.environ.get("TESTSRV_LINK_HOST", "")
BASE = os.environ.get("TESTSRV_BASE", "")
AUTH = os.environ.get("TESTSRV_AUTH", "")
SHOTS = os.environ.get("C4B_SHOTS", "")
COOKIE = "__Host-cc_link"
APPLE = "https://web.push.apple.com/c4b-validation"

pytestmark = pytest.mark.skipif(not (HOST and BASE and AUTH), reason="needs a slot from `scripts/testsrv lease --link`")


def totp_code(slot_dir: Path) -> str:
    secret = next(line.split("=", 1)[1].strip() for line in (slot_dir / ".env").read_text().splitlines()
                  if line.startswith("TOTP_SECRET="))
    used_file = slot_dir / "totp-used.json"
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    for _ in range(3):
        if 30 - time.time() % 30 < 4:
            time.sleep(5)
        used = json.loads(used_file.read_text()) if used_file.exists() else []
        now = int(time.time()) // 30
        for step in (now, now + 1, now - 1):
            digest = hmac.new(key, struct.pack(">Q", step), "sha1").digest()
            offset = digest[-1] & 15
            code = "%06d" % ((struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000)
            if code not in used:
                used_file.write_text(json.dumps((used + [code])[-9:]))
                return code
        time.sleep(30 - time.time() % 30 + 1)
    raise RuntimeError("no unused TOTP code")


def _fresh_keys() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    point = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    return {"p256dh": b64(point), "auth": b64(os.urandom(16))}


def shot(target, name: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        path = str(Path(SHOTS) / f"{name}.png")
        target.screenshot(path=path) if hasattr(target, "element_handle") else target.screenshot(path=path, full_page=True)


def theme_css(theme: str) -> str:
    manifest = json.loads((Path(__file__).resolve().parents[2] / f"client/css/themes/{theme}/theme.json").read_text())
    return ":root{" + ";".join(f"{k}:{v}" for k, v in manifest["cssVars"].items() if k.startswith("--color-")) + "}"


def cookie_names(context) -> list[str]:
    return [c["name"] for c in context.cookies()]


STANDALONE = """
Object.defineProperty(navigator, 'standalone', {get: () => true});
const realMatch = window.matchMedia.bind(window);
window.matchMedia = (q) => /display-mode:\\s*standalone/.test(q)
  ? {matches: true, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}}
  : realMatch(q);
"""


def devices_over_api(headers: dict) -> list:
    return httpx.get(f"{BASE}/api/v1/phone-link/devices", headers=headers).json()


def open_panel(dpage) -> object:
    dpage.evaluate("() => window.CloudeWeb.openSettingsScreen()")
    dpage.locator('.st-nav__item[data-section="remote"]').click()
    panel = dpage.locator('[data-setting-id="phone_link"]')
    panel.locator('[data-pl="panel"]').wait_for(state="visible", timeout=15000)
    return panel


def open_window(dpage, panel) -> dict:
    with dpage.expect_response(lambda r: r.url.endswith("/phone-link/pairing-window") and r.request.method == "POST") as info:
        panel.locator('[data-pl="pair"]').click()
    panel.locator('[data-pl="qr"]').wait_for(state="visible")
    return info.value.json()


def test_pair_flow_over_the_real_relay(request):
    from playwright.sync_api import sync_playwright

    slot_dir = Path(AUTH).parent
    link = f"https://{HOST}"
    with sync_playwright() as pw:
        webkit = pw.webkit.launch()
        iphone = {**pw.devices["iPhone 13"], "ignore_https_errors": True}
        desktop = webkit.new_context(storage_state=AUTH, viewport={"width": 1280, "height": 900}, ignore_https_errors=True)
        try:
            desktop_token = json.loads(Path(AUTH).read_text())["origins"][0]["localStorage"][0]["value"]
            headers = {"authorization": f"Bearer {desktop_token}"}
            for old in devices_over_api(headers):
                httpx.delete(f"{BASE}/api/v1/phone-link/devices/{old['id']}", headers=headers)
            dpage = desktop.new_page()
            dpage.goto(BASE)
            dpage.wait_for_function("() => window.CloudeWeb && window.CloudeWeb.openSettingsScreen && window.AppBootComplete"
                                    " && window.AppBootComplete.isComplete()", timeout=30000)
            panel = open_panel(dpage)
            assert panel.locator('[data-pl="switch"]').get_attribute("aria-checked") == "true"
            assert "staging" in panel.locator('[data-pl="cert"]').inner_text()
            shot(panel, "desktop-1-panel")
            window = open_window(dpage, panel)
            qr_url = window["url"]
            assert qr_url.startswith(f"{link}/pair#") and len(window["code"]) == 8 and window["pair_url"] == f"{link}/pair"
            assert window["qr"].startswith("data:image/png;base64,") and window["qr_rotate_seconds"] == 60
            assert panel.locator('[data-pl="code"]').count() == 0, "the typed code stays hidden until asked for"
            dpage.wait_for_function("() => /connected/.test(document.querySelector('[data-pl=\"tunnel\"]')?.textContent || '')",
                                    timeout=60000)
            assert re.search(r"closes in (9|10):\d\d", panel.locator('[data-pl="countdown"]').inner_text())
            shot(panel, "desktop-2-window-qr")

            safari = webkit.new_context(**iphone)
            spage = safari.new_page()
            spage.goto(qr_url)
            spage.locator('[data-pair="otp-code"]').wait_for(state="visible", timeout=30000)
            assert "#" not in spage.url, "the secret is stripped from the address bar"
            assert COOKIE not in cookie_names(safari), "a scan alone grants no pairing cookie"
            assert devices_over_api(headers) == [], "a scan alone creates no device row"
            shot(spage, "phone-1-code-step-default")
            spage.add_style_tag(content=theme_css("dracula"))
            shot(spage, "phone-1-code-step-dracula")
            panel.locator('[data-pl="scanned"]').wait_for(state="visible", timeout=15000)
            assert panel.locator('[data-pl="scanned"]').inner_text() == "phone scanned, waiting for its code"
            shot(panel, "desktop-3-scanned")

            spage.locator('[data-pair="otp-code"]').fill("000000")
            spage.locator('[data-pair="otp-submit"]').click()
            spage.locator('[data-pair-error="wrong_otp"]').wait_for(timeout=15000)
            assert COOKIE not in cookie_names(safari) and devices_over_api(headers) == [], "a wrong code pairs nothing"
            shot(spage, "phone-2-wrong-code-default")
            with pytest.raises(AssertionError):
                assert devices_over_api(headers) != []
            spage.locator('[data-pair="otp-code"]').fill(totp_code(slot_dir))
            spage.locator('[data-pair="otp-submit"]').click()
            spage.wait_for_url(re.compile(rf"^{re.escape(link)}/?$"), timeout=30000)
            assert COOKIE in cookie_names(safari)
            spage.wait_for_function("() => window.AppBootComplete && window.AppBootComplete.isComplete()", timeout=60000)
            assert spage.locator("#totp-input").count() == 0 or not spage.locator("#totp-input").is_visible(), \
                "pairing signed the phone in: no second code is asked"
            shot(spage, "phone-3-paired-and-in")
            (device,) = devices_over_api(headers)
            assert device["label"] == "iphone" and device["kind"] == "browser"
            panel.locator('[data-pl="paired"]').wait_for(state="visible", timeout=15000)
            assert panel.locator('[data-pl="paired"]').inner_text() == "paired: iphone"
            shot(panel, "desktop-4-paired")

            other = webkit.new_context(**iphone)
            opage = other.new_page()
            opage.goto(qr_url)
            opage.locator('[data-pair-error="link_used"]').wait_for(timeout=30000)
            assert COOKIE not in cookie_names(other) and len(devices_over_api(headers)) == 1
            shot(opage, "phone-4-second-scan-refused-default")
            opage.add_style_tag(content=theme_css("dracula"))
            shot(opage, "phone-4-second-scan-refused-dracula")
            opage.locator('[data-pair="no-camera"]').click()
            assert opage.locator('[data-pair="code"]').is_visible()
            shot(opage, "phone-5-no-camera-form")
            other.close()
            with dpage.expect_response(lambda r: r.url.endswith("/phone-link/pairing-window") and r.request.method == "POST") as info:
                panel.locator('[data-pl="again"]').click()
            second = info.value.json()
            panel.locator('[data-pl="qr"]').wait_for(state="visible", timeout=15000)
            spage.goto(second["url"])
            spage.wait_for_url(re.compile(rf"^{re.escape(link)}/?$"), timeout=30000)
            spage.wait_for_function("() => window.AppBootComplete && window.AppBootComplete.isComplete()", timeout=60000)
            assert len(devices_over_api(headers)) == 1, "a re-scan from a paired phone adds no device row"
            spage.evaluate("() => { localStorage.clear(); }")
            spage.goto(second["url"])
            spage.locator("#totp-input").wait_for(state="visible", timeout=30000)
            assert len(devices_over_api(headers)) == 1
            shot(spage, "phone-6-rescan-normal-login")
            safari.close()

            app = webkit.new_context(**iphone)
            app.add_init_script(STANDALONE)
            apage = app.new_page()
            apage.goto(f"{link}/pair")
            apage.locator('[data-pair="code"]').wait_for(state="visible", timeout=30000)
            assert "this app is not paired yet" in apage.locator(".pair__head").inner_text()
            shot(apage, "phone-7-installed-app-entry")
            apage.locator('[data-pair="code"]').fill("ZZZZZZZZ")
            apage.locator('[data-pair="submit"]').click()
            apage.locator('[data-pair-error="wrong_code"]').wait_for(timeout=15000)
            assert COOKIE not in cookie_names(app), "a wrong code must grant no cookie"
            apage.locator('[data-pair="code"]').fill(second["code"])
            apage.locator('[data-pair="submit"]').click()
            apage.locator('[data-pair="otp-code"]').wait_for(state="visible", timeout=15000)
            assert COOKIE not in cookie_names(app) and len(devices_over_api(headers)) == 1, "the typed code alone pairs nothing"
            apage.locator('[data-pair="otp-code"]').fill(totp_code(slot_dir))
            apage.locator('[data-pair="otp-submit"]').click()
            apage.wait_for_url(re.compile(rf"^{re.escape(link)}/?$"), timeout=30000)
            apage.wait_for_function("() => window.AppBootComplete && window.AppBootComplete.isComplete()", timeout=60000)
            assert COOKIE in cookie_names(app) and len(devices_over_api(headers)) == 2

            token = apage.evaluate("() => localStorage.getItem('claude_tunnel_token')")
            made = apage.evaluate(
                """async ([token, body]) => { const r = await fetch('/api/v1/push/subscriptions', {method: 'POST',
                headers: {'content-type': 'application/json', authorization: 'Bearer ' + token}, body: JSON.stringify(body)});
                return [r.status, await r.json()]; }""", [token, {"endpoint": APPLE, "keys": _fresh_keys(), "device_id": "forged"}])
            assert made[0] == 201 and made[1]["device_id"] not in (None, "forged")
            device_id = made[1]["device_id"]
            denied = apage.evaluate(
                """async (token) => (await fetch('/api/v1/phone-link/devices', {headers: {authorization: 'Bearer ' + token}})).status""", token)
            assert denied == 403

            dpage.wait_for_function("() => document.querySelectorAll('[data-pl-device]').length === 2", timeout=15000)
            row = dpage.locator(f'[data-pl-device="{device_id}"]')
            row.wait_for(state="visible")
            assert "last seen" in row.inner_text() and "alerts on" in row.locator('[data-pl="push"]').inner_text()
            shot(panel, "desktop-5-devices")
            row.locator('[data-pl="revoke"]').click()
            row.wait_for(state="detached", timeout=15000)
            apage.goto(f"{link}/")
            apage.wait_for_url(re.compile(r"/pair$"), timeout=30000)
            subs = dpage.evaluate(
                """async (t) => (await (await fetch('/api/v1/push/subscriptions', {headers: {authorization: 'Bearer ' + t}})).json())""",
                desktop_token)
            assert subs["subscriptions"] == [], "revoking a device removes its push subscriptions"

            prefs = dpage.evaluate("""async (t) => (await (await fetch('/api/v1/preferences', {headers: {authorization: 'Bearer ' + t}})).json()).revision""", desktop_token)
            dpage.evaluate(
                """async ([t, rev]) => fetch('/api/v1/preferences', {method: 'PATCH', headers: {authorization: 'Bearer ' + t,
                'content-type': 'application/json'}, body: JSON.stringify({changes: {theme: 'dracula'}, expected_revision: rev})})""",
                [desktop_token, prefs])
            dpage.reload()
            dpage.wait_for_function("() => window.CloudeWeb && window.AppBootComplete && window.AppBootComplete.isComplete()", timeout=30000)
            shot(open_panel(dpage), "desktop-6-panel-dracula")
        finally:
            for context in list(webkit.contexts):
                context.close()
            webkit.close()
