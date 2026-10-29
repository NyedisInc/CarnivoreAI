
from __future__ import annotations

import functools
import http.server
import re
import threading
from pathlib import Path

import pytest

from tests.python.design_system._sources import css_of

CLIENT = Path(__file__).resolve().parents[3] / "client"
SHARED = CLIENT / "css" / "modal-titlerow.css"
SHARED_PROPS = ("display", "align-items", "min-height", "height", "padding", "background", "box-shadow")

WEARERS = {
    "restart-picker__head": ("session-restart-picker.css", "session-restart-picker.js"),
    "sidebar-help__lightbox-bar": ("media-lightbox.css", None),
    "restore-offer__head": ("session-restore-offer.css", "session-restore-offer.js"),
    "group-colour-picker__title": ("session-sidebar-colours.css", "../../web/src/lib/drawer/GroupColorPicker.svelte"),
    "text-prompt-modal__head": ("text-prompt-modal.css", None),
}


def own_declarations(css: str, cls: str) -> set[str]:
    found: set[str] = set()
    for match in re.finditer(r"(?:^|[{};\s])\." + re.escape(cls) + r"\s*\{([^}]*)\}", css):
        found |= set(re.findall(r"([\w-]+)\s*:", match.group(1)))
    return found


def test_scan_can_go_red():
    sample = ".x__head { gap: 4px; padding: 0 16px; min-height: 26px; }"
    assert own_declarations(sample, "x__head") & set(SHARED_PROPS) == {"padding", "min-height"}


def test_shared_rule_is_the_restart_picker_row():
    css = css_of(SHARED)
    body = re.search(r"\.modal-titlerow,\s*\.text-prompt-modal__head\s*\{([^}]*)\}", css)
    assert body, "modal-titlerow.css lost its shared rule"
    assert "min-height: var(--oc-titlerow-h, 37px)" in body.group(1)
    assert "padding: 0 14px" in body.group(1)
    assert "var(--oc-ground-titlerow)" in body.group(1)


@pytest.mark.parametrize("cls", sorted(WEARERS))
def test_no_dialog_redeclares_the_strip(cls):
    sheet, js = WEARERS[cls]
    redeclared = own_declarations(css_of(CLIENT / "css" / sheet), cls) & set(SHARED_PROPS)
    assert not redeclared, f".{cls} in {sheet} redeclares {sorted(redeclared)}: that is a sixth copy of the title row"
    if js:
        markup = (CLIENT / "js" / js).resolve().read_text(encoding="utf-8")
        assert re.search(r'class="[^"]*\bmodal-titlerow\b[^"]*\b' + re.escape(cls) + r"\b", markup), (
            f"{js} builds .{cls} without .modal-titlerow"
        )


def test_the_guide_registers_the_class():
    registry = (CLIENT / "style-guide" / "registry.json").read_text(encoding="utf-8")
    assert '"client/css/modal-titlerow.css"' in registry and '"modal-titlerow"' in registry


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
<link rel="stylesheet" href="/css/confirm-modal.css">
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


def test_confirm_dialog_strip_is_the_shared_class():
    markup = (CLIENT / "js" / "app.js").read_text(encoding="utf-8")
    assert '<div class="modal-titlerow"><span class="confirm-modal__verb">' in markup
    assert "confirm-modal__head" not in css_of(CLIENT / "css" / "confirm-modal.css")


def test_lightbox_bar_markup_wears_the_shared_class():
    svelte = (CLIENT.parent / "web" / "src" / "lib" / "help" / "MediaLightbox.svelte").read_text(encoding="utf-8")
    assert 'class="modal-titlerow sidebar-help__lightbox-bar"' in svelte


def test_help_header_is_left_alone():
    assert "padding" in own_declarations(css_of(CLIENT / "css" / "sidebar-help.css"), "sidebar-help__header")
