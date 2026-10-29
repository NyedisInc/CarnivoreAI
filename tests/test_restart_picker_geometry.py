
from __future__ import annotations

import http.server
import json
import os
import socket
import socketserver
import threading
from pathlib import Path

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so NOTHING about the restart picker's "
        "geometry was measured. This is a could-not-evaluate, not a pass."
    ),
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_ROOT = REPO_ROOT / "client"

PHONE = {"width": 390, "height": 844}

DESKTOP = {"width": 1280, "height": 900}

EPSILON_PX = 0.5

CSS_FILES = [
    "css/styles.css",
    "css/modal-titlerow.css",
    "css/session-restart-picker.css",
    "dist/app.css",
]

JS_FILES = [
    "js/session-status-ui.js",
    "js/session-restart-live.js",
    "js/session-restart-options.js",
    "js/session-restart-picker.js",
]

GONE = (
    "no transcript for claude session db81f6bf-85f9-448b-a7f6-bc83f62659d9 "
    "exists under /Users/sam/.claude/projects, so it cannot be resumed"
)

WRAPPER_LABELS = [
    "claude (keychain-backed)",
    "cldl (openrouter)",
    "cldl (lmstudio)",
    "claude-chrome",
    "claude (npm global)",
]


def _gone_option(agent_type: str, label: str) -> dict:
    return {
        "agent_type": agent_type,
        "label": label,
        "is_current": False,
        "resolvable": True,
        "actionable_now": False,
        "kind": "transcript_missing",
        "detail": GONE,
        "projected_kind": "transcript_missing",
        "projected_detail": GONE,
        "command": None,
        "conversation": "unknown",
    }


PREVIEW_GONE = {
    "name": "media-compression",
    "current_agent_type": "claude",
    "pane_state": "dead",
    "unchanged": {
        "kind": "transcript_missing",
        "detail": GONE,
        "command": None,
        "actionable": False,
        "conversation": "unknown",
    },
    "projected": {
        "kind": "transcript_missing",
        "detail": GONE,
        "command": None,
        "actionable": False,
        "conversation": "unknown",
    },
    "options": [
        _gone_option("w%d" % i, label)
        for i, label in enumerate(WRAPPER_LABELS)
    ],
    "wrappers_status": "ok",
}

PREVIEW_VARIED = {
    "name": "media-compression",
    "current_agent_type": "claude",
    "pane_state": "dead",
    "unchanged": {
        "kind": "replay",
        "detail": (
            "restarting the command tmux recorded for this pane, and whether "
            "it comes back on the same conversation could not be determined, "
            "so treat its history as at risk"
        ),
        "command": None,
        "actionable": True,
        "conversation": "unknown",
    },
    "projected": {
        "kind": "replay",
        "detail": (
            "restarting the command tmux recorded for this pane, and whether "
            "it comes back on the same conversation could not be determined, "
            "so treat its history as at risk"
        ),
        "command": None,
        "actionable": True,
        "conversation": "unknown",
    },
    "options": [
        {
            "agent_type": "w%d" % i,
            "label": label,
            "is_current": False,
            "resolvable": True,
            "actionable_now": True,
            "kind": "agent",
            "detail": (
                f"starting {label}, which you picked, instead of what this "
                f"session was launched with, resuming the same conversation "
                f"it is on now"
            ),
            "projected_kind": "agent",
            "projected_detail": (
                f"starting {label}, which you picked, instead of what this "
                f"session was launched with, resuming the same conversation "
                f"it is on now"
            ),
            "command": "run-%d" % i,
            "conversation": "resumed",
        }
        for i, label in enumerate(WRAPPER_LABELS)
    ],
    "wrappers_status": "ok",
}

MIXED_KEEP = "restarting the command tmux recorded for this pane, resuming it"
MIXED_CHOSEN = (
    "starting claude-chrome, which you picked, instead of what this session "
    "was launched with, resuming the same conversation"
)

PREVIEW_MIXED = {
    "name": "media-compression",
    "current_agent_type": "claude",
    "pane_state": "dead",
    "unchanged": {
        "kind": "replay",
        "detail": MIXED_KEEP,
        "command": None,
        "actionable": True,
        "conversation": "resumed",
    },
    "projected": {
        "kind": "replay",
        "detail": MIXED_KEEP,
        "command": None,
        "actionable": True,
        "conversation": "resumed",
    },
    "options": [
        {
            "agent_type": "claude-chrome",
            "label": "claude-chrome",
            "is_current": False,
            "resolvable": True,
            "actionable_now": True,
            "kind": "agent",
            "detail": MIXED_CHOSEN,
            "projected_kind": "agent",
            "projected_detail": MIXED_CHOSEN,
            "command": "run-cc",
            "conversation": "resumed",
        },
        _gone_option("cldl", "cldl (openrouter)"),
    ],
    "wrappers_status": "ok",
}

HARNESS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
__CSS__
<style>
  :root {
    --color-bg: #1e1e1e; --color-bg-hover: #2c2c2c; --color-bg-elevated: #262626;
    --color-fg: #ddd; --color-fg-strong: #fff; --color-fg-subtle: #999;
    --color-accent: #7aa2f7; --color-border: #444; --color-border-subtle: #3a3a3a;
    --border-color: #444; --accent-color: #7aa2f7; --text-muted: #999;
    --success-color: #5c9d78; --warning-color: #d9a000;
    --danger-color: #e06c75;
    --radius-sm: 3px; --radius-md: 6px;
  }
  html, body { margin: 0; background: var(--color-bg); color: var(--color-fg); }
</style>
</head>
<body>
__JS__
<script>
window.__preview = null;
window.API = {
  restartPreview: function () { return Promise.resolve(window.__preview); },
};
window.App = {
  showConfirmModal: function () { return Promise.resolve(false); },
};
window.__open = function (preview) {
  window.__preview = preview;
  window.SessionRestartPicker.open('row-dead', 'Media Compression', null);
};
</script>
</body>
</html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _ClientHandler(http.server.SimpleHTTPRequestHandler):

    def translate_path(self, path: str) -> str:  # noqa: D102
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/static/"):
            return str(CLIENT_ROOT / clean[len("/static/"):])
        return str(CLIENT_ROOT / clean.lstrip("/"))

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] in ("/", "/index.html"):
            body = _harness_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args) -> None:  # noqa: D102
        return


def _harness_html() -> str:
    css = "\n".join(
        f'<link rel="stylesheet" href="/static/{name}">' for name in CSS_FILES
    )
    js = "\n".join(f'<script src="/static/{name}"></script>' for name in JS_FILES)
    js += '\n<script type="module" src="/static/js/i18n/boot.js"></script>'
    js += '\n<script type="module" src="/static/dist/app.js"></script>'
    return HARNESS_HTML.replace("__CSS__", css).replace("__JS__", js)


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), _ClientHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _measure(base_url, preview, viewport):
    from playwright.sync_api import sync_playwright

    headed = os.environ.get("CLOUDE_TEST_HEADED") == "1"
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=not headed, args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(
                f"chromium could not launch ({exc}), so NOTHING about the "
                "restart picker's geometry was measured. Not a pass."
            )
        context = browser.new_context(viewport=viewport, device_scale_factor=1)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base_url, wait_until="load")
        assert page.evaluate("document.hidden") is False, (
            "the page reports document.hidden; a backgrounded tab freezes its "
            "render loop and every measurement below would be manufactured"
        )
        assert page.evaluate("!!window.SessionRestartPicker"), (
            "session-restart-picker.js did not load"
        )
        page.evaluate("p => window.__open(p)", preview)
        page.wait_for_selector(".restart-picker__choice [data-choice-trigger]", state="visible")
        page.wait_for_function(
            "() => getComputedStyle(document.querySelector('.restart-picker__content')).transform === 'none'"
        )
        page.click(".restart-picker__choice [data-choice-trigger]")
        page.wait_for_selector("[data-choice-option]", state="visible")
        measured = page.evaluate(
            """() => {
                const list = document.querySelector('[data-choice-list]');
                const rows = Array.from(
                    document.querySelectorAll('[data-choice-option]'));
                const box = el => {
                    const r = el.getBoundingClientRect();
                    return {
                        top: r.top, bottom: r.bottom,
                        left: r.left, right: r.right,
                        width: r.width, height: r.height,
                    };
                };
                return {
                    list: {
                        rect: box(list),
                        scrollHeight: list.scrollHeight,
                        clientHeight: list.clientHeight,
                        overflowY: getComputedStyle(list).overflowY,
                    },
                    rows: rows.map(el => {
                        const detail = el.querySelector(
                            '.cdd__sr[id$="-hint"]');
                        const title = el.querySelector(
                            '.lpd-label');
                        const body = el.querySelector(
                            '.lpd-main');
                        return {
                            title: title ? title.textContent.trim() : '',
                            rect: box(el),
                            scrollHeight: el.scrollHeight,
                            clientHeight: el.clientHeight,
                            titleRect: title ? box(title) : null,
                            bodyRect: body ? box(body) : null,
                            detailRect: detail ? box(detail) : null,
                            detailText: detail
                                ? detail.textContent.trim() : '',
                        };
                    }),
                };
            }"""
        )
        assert not errors, f"the page threw: {errors}"
        context.close()
        browser.close()
    return measured


def _intersection(a: dict, b: dict) -> tuple:
    vertical = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
    horizontal = min(a["right"], b["right"]) - max(a["left"], b["left"])
    return vertical, horizontal


LAYOUTS = [
    (DESKTOP, "desktop", "gone"),
    (PHONE, "phone", "gone"),
    (DESKTOP, "desktop", "varied"),
    (PHONE, "phone", "varied"),
]


def _payload(which):
    return {"gone": PREVIEW_GONE, "varied": PREVIEW_VARIED}[which]


@pytest.mark.parametrize("viewport,name,which", LAYOUTS)
def test_no_two_option_rows_overlap(base_url, viewport, name, which):
    measured = _measure(base_url, _payload(which), viewport)
    rows = measured["rows"]
    assert len(rows) == len(WRAPPER_LABELS) + 1, (
        f"expected the baseline row plus {len(WRAPPER_LABELS)} wrappers, "
        f"got {len(rows)} on {name}"
    )
    for i in range(len(rows)):
        for j in range(len(rows)):
            if i == j:
                continue
            mine = rows[i]["detailRect"] or rows[i]["bodyRect"]
            theirs = rows[j]["titleRect"]
            if mine is None or theirs is None:
                continue
            vertical, horizontal = _intersection(mine, theirs)
            assert not (vertical > EPSILON_PX and horizontal > EPSILON_PX), (
                f"on {name} the text of option row {i} "
                f"({rows[i]['title']!r}) is painted over the title of row {j} "
                f"({rows[j]['title']!r}), overlapping by {vertical:.1f}px. "
                f"row {i}'s text runs {mine['top']:.1f}..{mine['bottom']:.1f}, "
                f"row {j}'s title sits at "
                f"{theirs['top']:.1f}..{theirs['bottom']:.1f}. that is text on "
                "top of text."
            )
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            vertical, horizontal = _intersection(
                rows[i]["rect"], rows[j]["rect"]
            )
            assert not (vertical > EPSILON_PX and horizontal > EPSILON_PX), (
                f"on {name} option row {i} ({rows[i]['title']!r}) and row {j} "
                f"({rows[j]['title']!r}) intersect by {vertical:.1f}px"
            )


@pytest.mark.parametrize("viewport,name,which", LAYOUTS)
def test_every_option_row_contains_its_own_text(base_url, viewport, name, which):
    measured = _measure(base_url, _payload(which), viewport)
    for i, row in enumerate(measured["rows"]):
        assert row["scrollHeight"] <= row["clientHeight"] + EPSILON_PX, (
            f"on {name} option row {i} ({row['title']!r}) holds "
            f"{row['scrollHeight']}px of content in a {row['clientHeight']}px "
            f"box, so {row['scrollHeight'] - row['clientHeight']}px of text is "
            "escaping or being clipped"
        )


@pytest.mark.parametrize("viewport,name,which", LAYOUTS)
def test_no_detail_line_is_drawn_outside_its_own_row(
    base_url, viewport, name, which
):
    measured = _measure(base_url, _payload(which), viewport)
    for i, row in enumerate(measured["rows"]):
        detail = row["detailRect"]
        if detail is None:
            continue
        assert detail["bottom"] <= row["rect"]["bottom"] + EPSILON_PX, (
            f"on {name} the detail line of row {i} ({row['title']!r}) ends at "
            f"{detail['bottom']:.1f} but its row ends at "
            f"{row['rect']['bottom']:.1f}, so it is painted outside the row"
        )
        assert detail["top"] >= row["rect"]["top"] - EPSILON_PX, (
            f"on {name} the detail line of row {i} ({row['title']!r}) starts "
            f"above its own row"
        )


def test_the_list_scrolls_rather_than_squashing_its_rows(base_url):
    many = json.loads(json.dumps(PREVIEW_VARIED))
    many["options"] = [
        dict(o, agent_type=f"{o['agent_type']}-{n}")
        for n in range(4) for o in PREVIEW_VARIED["options"]
    ]
    measured = _measure(base_url, many, PHONE)
    lst = measured["list"]
    assert lst["overflowY"] in ("auto", "scroll"), (
        f"the option list is not scrollable ({lst['overflowY']}), so content "
        "past its max-height has nowhere to go"
    )
    total = sum(r["rect"]["height"] for r in measured["rows"])
    assert total > lst["clientHeight"], (
        "this payload no longer overflows the list at phone width, so it is "
        f"not exercising the bug any more (rows {total:.0f}px, list "
        f"{lst['clientHeight']:.0f}px). Lengthen the fixture."
    )
    assert lst["scrollHeight"] > lst["clientHeight"], (
        "the rows are taller than the list but the list reports no scrollable "
        f"content ({lst['scrollHeight']} vs {lst['clientHeight']}), which "
        "means the rows were compressed to fit instead of the list scrolling"
    )
