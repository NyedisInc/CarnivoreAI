
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parents[3] / "client"


HEADS = "".join(
    f'<div class="{extra}{cls}" id="{cls}"><span>title</span></div>'
    for cls, extra in [
        ("restart-picker__head", "modal-titlerow "),
        ("sidebar-help__lightbox-bar", "modal-titlerow "),
        ("restore-offer__head", "modal-titlerow "),
        ("group-colour-picker__title", "modal-titlerow "),
        ("text-prompt-modal__head", ""),
    ]
)

PAGE = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="/css/layers.css"><link rel="stylesheet" href="/css/styles.css">
<link rel="stylesheet" href="/dist/app.css">
<link rel="stylesheet" href="/css/session-sidebar-colours.css">
<link rel="stylesheet" href="/css/modal-titlerow.css">
<link rel="stylesheet" href="/css/session-restart-picker.css">
<link rel="stylesheet" href="/css/text-prompt-modal.css">
<link rel="stylesheet" href="/css/session-restore-offer.css">
<link rel="stylesheet" href="/css/media-lightbox.css">
</head><body>%s</body></html>""" % HEADS

PROBE = """() => Object.fromEntries([...document.body.children].map((el) => {
  const cs = getComputedStyle(el);
  return [el.id, { h: el.getBoundingClientRect().height, pl: cs.paddingLeft, pr: cs.paddingRight, bg: cs.backgroundColor,
                   shadow: cs.boxShadow }];
}))"""


@pytest.fixture(scope="module")
def measured():
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the strips were NOT measured")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] == "/rows.html":
                body = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(CLIENT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            server.shutdown()
            pytest.skip(f"chromium unavailable: {exc}")
        page = browser.new_page(viewport={"width": 900, "height": 600})
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/rows.html")
        page.wait_for_timeout(300)
        result = page.evaluate(PROBE)
        browser.close()
    server.shutdown()
    return result


def test_every_strip_measures_like_the_restart_picker_row(measured):
    reference = measured["restart-picker__head"]
    assert reference["h"] == 37 and reference["pl"] == "14px", reference
    for cls, got in measured.items():
        assert (got["h"], got["pl"], got["pr"]) == (reference["h"], "14px", "14px"), f".{cls}: {got}"
        assert got["shadow"] == reference["shadow"] and got["bg"] == reference["bg"], f".{cls}: {got}"
