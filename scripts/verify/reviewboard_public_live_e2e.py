
from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SLOT = os.environ.get("TESTSRV_SLOT", "1")
SLOT_DIR = Path.home() / "dev-worktrees" / ".testsrv" / f"slot{SLOT}"
BASE = f"http://127.0.0.1:{8100 + int(SLOT)}"
API = f"{BASE}/api/v1"
OUT = Path(os.environ.get("OUT", "/tmp/reviewboard-public-live-e2e"))
SLUG = "20261102-e2e-live"
HOST_NAME = "pb.test.local"
LISTEN_PORT = 5131
PROXY_PORT = 5132
APPEAR_S, LEAVE_S = 3.0, 35.0

RESULTS: List[Tuple[str, bool, str]] = []
PAUSE: List[Callable[[float], None]] = [time.sleep]


def lan_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 1))
        return str(probe.getsockname()[0])


def owner_token() -> str:
    state = json.loads((SLOT_DIR / "auth-state.json").read_text())
    return next(i["value"] for i in state["origins"][0]["localStorage"] if i["name"] == "claude_tunnel_token")


def call(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {owner_token()}", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as out:
            return out.status, json.loads(out.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:300]


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def enable_plugins(address: str) -> None:
    for cplug, body in (("reviewboard", {"grants": {"app": ["agent_writes", "notify"]},
                                         "settings": {"publicLinksEnabled": True, "port": LISTEN_PORT, "bindAddress": address, "hostnames": HOST_NAME,
                                                      "trustedProxies": address}}),):
        rows = call("GET", "/cplugs")[1]
        rows = rows if isinstance(rows, list) else rows["cplugs"]
        revision = next(r["revision"] for r in rows if r["id"] == cplug)
        status, out = call("PUT", f"/cplugs/{cplug}", {"enabled": True, "revision": revision, **body})
        if status != 200:
            raise SystemExit(f"could not enable {cplug}: {status} {out}")


def make_board() -> None:
    folder = SLOT_DIR / "state" / "review-boards" / SLUG
    folder.mkdir(parents=True, exist_ok=True)
    revisions = []
    for n in (1, 2):
        html = (f"<!doctype html><title>bar {n}</title><body style='font:14px sans-serif;padding:24px'><h2>bottom bar, version {n}</h2></body>\n").encode()
        (folder / f"r00{n}.html").write_bytes(html)
        revisions.append({"id": f"r{n}", "n": n, "created_at": f"2026-11-02T1{n}:00:00Z", "by": {"actor": "claude", "session": "ses_e2e"}, "summary": f"version {n}",
                          "answers_round": None, "viewport": 600,
                          "views": [{"id": "main", "label": "bar", "file": f"r00{n}.html", "sha256": hashlib.sha256(html).hexdigest(), "bytes": len(html)}],
                          "prompts": [{"id": "padding", "kind": "check", "label": "padding looks right"},
                                      {"id": "layout", "kind": "choice", "label": "which row", "options": [{"id": "a", "label": "one"}, {"id": "b", "label": "two"}]}],
                          "anchors": []})
    raw = {"schema": "carnivore.reviewboard.sidecar", "schema_version": 1,
           "board": {"slug": SLUG, "title": "e2e live board", "kind": "mockup", "created_at": "2026-11-02T10:00:00Z", "created_by": {"actor": "claude", "session": "ses_e2e"}},
           "task": {"item_id": 1, "list": "project:18", "computer": "mac-mini-m4", "github_issue": "x/y#1", "title_at_link": "e2e", "linked_at": "2026-11-02T10:00:00Z", "history": []},
           "revisions": revisions, "rounds": [], "ext": {}}
    (folder / "sidecar.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    call("POST", "/cplugs/reviewboard/rescan", {})


class _Forward(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"
    upstream: Tuple[str, int] = ("127.0.0.1", LISTEN_PORT)

    def log_message(self, *_a: Any) -> None:
        return

    def _relay(self) -> None:
        size = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(size) if size else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection", "x-forwarded-for")}
        headers.update({"Host": HOST_NAME, "X-Forwarded-For": "198.51.100.7"})
        conn = http.client.HTTPConnection(*self.upstream, timeout=120)
        conn.request(self.command, self.path, body, headers)
        res = conn.getresponse()
        data = res.read()
        self.send_response(res.status)
        for key, value in res.getheaders():
            if key.lower() not in ("transfer-encoding", "connection", "content-length"):
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _relay


def start_proxy(address: str) -> ThreadingHTTPServer:
    _Forward.upstream = (address, LISTEN_PORT)
    server = ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), _Forward)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def wait_for(read: Callable[[], Any], ok: Callable[[Any], bool], seconds: float) -> Tuple[Optional[float], Any]:
    started = time.time()
    value = read()
    while time.time() - started < seconds:
        value = read()
        if ok(value):
            return round(time.time() - started, 1), value
        PAUSE[0](0.2)
    return None, value


def main() -> int:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    OUT.mkdir(parents=True, exist_ok=True)
    address = lan_ip()
    enable_plugins(address)
    make_board()
    start_proxy(address)
    call("DELETE", f"/cplugs/reviewboard/public/links?board={SLUG}")
    for row in call("GET", f"/cplugs/reviewboard/public/visitors?board={SLUG}")[1].get("visitors", []):
        call("DELETE", f"/cplugs/reviewboard/public/visitors/u/{row['number']}?board={SLUG}")
    status, made = call("POST", "/cplugs/reviewboard/public/links", {"board": SLUG, "ttl": "1d", "mode": "follow", "access": "answer"})
    if status != 201:
        raise SystemExit(f"could not mint a link: {status} {made}")
    token = made["token"]

    def board_frame(page: Any) -> Any:
        return next((f for f in page.frames if "tab=reviewboard" in f.url and SLUG in f.url), None)

    def in_frame(page: Any, js: str) -> Any:
        for _ in range(15):
            try:
                frame = board_frame(page)
                if frame:
                    return frame.evaluate(js)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
        return None

    chips = "[...document.querySelectorAll('[data-history=visitor]')].map(e=>e.getAttribute('data-visitor'))"
    marked = "[...document.querySelectorAll('[data-history=visitor][data-present]')].map(e=>e.getAttribute('data-visitor'))"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        owner = browser.new_context(storage_state=str(SLOT_DIR / "auth-state.json"), viewport={"width": 1400, "height": 900})
        page = owner.new_page()
        PAUSE[0] = lambda seconds: page.wait_for_timeout(int(seconds * 1000))
        page.goto(BASE + "/")
        time.sleep(4)
        call("POST", f"/cplugs/reviewboard/boards/{SLUG}/open", {})
        wait_for(lambda: in_frame(page, "document.querySelectorAll('[data-history=revision]').length"), lambda n: bool(n), 20)
        before = in_frame(page, chips) or []
        visitor = browser.new_context(viewport={"width": 1200, "height": 800}).new_page()
        visitor.goto(f"http://127.0.0.1:{PROXY_PORT}/#{token}")
        visitor.wait_for_selector("[data-visitor-bar]", timeout=20000)
        took, seen = wait_for(lambda: call("GET", f"/cplugs/reviewboard/public/visitors?board={SLUG}")[1], lambda b: isinstance(b, dict) and b.get("viewing", 0) >= 1, APPEAR_S + 6)
        check("a visitor that has only opened the page is counted as viewing", took is not None, f"{took}s" if took is not None else str(seen)[:120])
        visitor.query_selector_all("input[type=checkbox], input[type=radio]")[0].check()
        took, seen = wait_for(lambda: in_frame(page, chips) or [], lambda c: len(c) > len(before), APPEAR_S)
        check("the u chip appears on the owner's open board with no reload", took is not None, f"{took}s" if took is not None else str(seen))
        number = (seen[-1] if seen else "u?").lstrip("u")
        took, seen = wait_for(lambda: in_frame(page, marked) or [], lambda c: f"u{number}" in c, APPEAR_S)
        check("the chip wears the live presence mark while the visitor is on the page", took is not None, f"{took}s" if took is not None else str(seen))
        marked_seen = took is not None
        page.screenshot(path=str(OUT / "owner-live-u-chip-with-presence.png"))
        in_frame(page, "document.querySelector('[aria-label=\"visitor answers\"]').click()")
        PAUSE[0](1.0)
        tagged = in_frame(page, f"!!document.querySelector('[data-visitor-present=u{number}]')")
        check("the visitors window tags the present visitor", bool(tagged))
        page.screenshot(path=str(OUT / "owner-visitors-window-viewing-now.png"))
        page.keyboard.press("Escape")
        PAUSE[0](0.5)
        in_frame(page, f"document.querySelector('[data-visitor=u{number}]').click()")
        PAUSE[0](1.5)
        reads: List[str] = []
        page.on("request", lambda r: reads.append(r.url))
        visitor.query_selector_all("input[type=checkbox], input[type=radio]")[1].check()
        took, seen = wait_for(lambda: [u for u in reads if f"/visitors/u/{number}" in u or "/visitors?board" in u], lambda r: bool(r), APPEAR_S)
        check("an open u view reads again after the visitor edits", took is not None, f"{took}s" if took is not None else "no read")
        visitor.close()
        took, seen = wait_for(lambda: in_frame(page, marked) or [], lambda c: f"u{number}" not in c, LEAVE_S)
        check("the presence mark clears after the visitor leaves (and was shown before)", took is not None and marked_seen, f"{took}s" if took is not None else str(seen))
        status, live = call("POST", "/cplugs/reviewboard/public/links", {"board": SLUG, "ttl": "1d", "mode": "pinned", "access": "answer"})
        call("DELETE", f"/cplugs/reviewboard/public/links/{made['link']['id']}")
        in_frame(page, "document.querySelector('[aria-label=\"share publicly\"]').click()")
        wait_for(lambda: in_frame(page, "document.querySelectorAll('[data-share-row]').length"), lambda n: bool(n), 5)
        rows_before = in_frame(page, "document.querySelectorAll('[data-share-row]').length")
        has_key = in_frame(page, "!!document.querySelector('[data-share-clear-ended]')")
        check("the share window offers clear ended when a link has ended", bool(has_key), f"{rows_before} rows")
        if has_key:
            page.screenshot(path=str(OUT / "owner-share-window-before-clear.png"))
            in_frame(page, "document.querySelector('[data-share-clear-ended]').click()")
            took, seen = wait_for(lambda: in_frame(page, "[...document.querySelectorAll('[data-share-row]')].map(e=>e.getAttribute('data-share-row'))"),
                                  lambda ids: isinstance(ids, list) and ids == [live['link']['id']], 5)
            check("clear ended removes every ended link and keeps the live one, with no reopen", took is not None, f"{took}s" if took is not None else str(seen))
        page.screenshot(path=str(OUT / "owner-share-window-after-clear.png"))
        browser.close()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
