
from __future__ import annotations

import base64
import functools
import hashlib
import http.server
import re
import socketserver
import sys
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.security_headers import SECURITY_HEADERS, build_csp  # noqa: E402

_INLINE_SCRIPT = re.compile(
    rb"<script(?![^>]*\ssrc\s*=)[^>]*>(.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)

VIOLATION_GLOBAL = "__cspViolations"


def script_hashes(html: bytes) -> list[str]:
    out = []
    for body in _INLINE_SCRIPT.findall(html):
        digest = hashlib.sha256(body).digest()
        out.append("'sha256-%s'" % base64.b64encode(digest).decode("ascii"))
    return out


class CSPStaticHandler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
        return

    def translate_path(self, path: str) -> str:
        if path.startswith("/static/"):
            path = "/client/" + path[len("/static/"):]
        return super().translate_path(path)

    def _stamp(self, csp: str | None = None) -> None:
        for name, value in SECURITY_HEADERS.items():
            if name == "Content-Security-Policy" and csp:
                self.send_header(name, csp)
            else:
                self.send_header(name, value)

    def end_headers(self) -> None:  # noqa: D102
        if not getattr(self, "_headers_already_stamped", False):
            self._stamp()
        super().end_headers()

    def do_GET(self) -> None:  # noqa: D102, N802
        path = Path(self.translate_path(self.path))
        if path.is_file() and path.suffix.lower() in (".html", ".htm"):
            self._send_html(path)
            return
        super().do_GET()

    def _send_html(self, path: Path) -> None:
        body = path.read_bytes()
        extra = " ".join(script_hashes(body))
        self._headers_already_stamped = True
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._stamp(build_csp(extra))
        self.end_headers()
        self.wfile.write(body)


def serve(root: Path) -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(CSPStaticHandler, directory=str(root))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def collector_init_script() -> str:
    return (
        "window.%s = [];\n"
        "document.addEventListener('securitypolicyviolation', function (e) {\n"
        "    window.%s.push({\n"
        "        directive: e.effectiveDirective || e.violatedDirective,\n"
        "        blocked: e.blockedURI,\n"
        "        sample: e.sample || '',\n"
        "        line: e.lineNumber || 0,\n"
        "        source: e.sourceFile || ''\n"
        "    });\n"
        "});\n" % (VIOLATION_GLOBAL, VIOLATION_GLOBAL)
    )


def violations(page) -> list[dict]:
    return page.evaluate("window.%s || []" % VIOLATION_GLOBAL) or []


def assert_collector_live(page) -> str | None:
    try:
        ok = page.evaluate(
            "() => {\n"
            "  const before = (window.%s || []).length;\n"
            "  if (!Array.isArray(window.%s)) return 'collector array absent';\n"
            "  const ev = new SecurityPolicyViolationEvent(\n"
            "      'securitypolicyviolation',\n"
            "      {violatedDirective: '__probe__',"
            "       effectiveDirective: '__probe__', blockedURI: 'probe'});\n"
            "  document.dispatchEvent(ev);\n"
            "  const after = window.%s.length;\n"
            "  if (after !== before + 1) return 'listener did not fire';\n"
            "  window.%s.splice(before, 1);\n"
            "  return '';\n"
            "}" % (VIOLATION_GLOBAL, VIOLATION_GLOBAL,
                   VIOLATION_GLOBAL, VIOLATION_GLOBAL)
        )
    except Exception as exc:  # noqa: BLE001
        return "CSP violation collector could not be probed: %s" % exc
    return ok or None


def assert_policy_served(response) -> str | None:
    """Prove the document really arrived carrying a script-src policy.

    Inputs:
        response: the playwright Response returned by page.goto(). A CSP
            header is NOT readable from JS, so it has to be read off the
            wire; asking the document is not an option.
    Output:
        None if `script-src` is in force, else a reason string.

    Same reasoning as the collector control. If the header never arrived,
    every CSP assertion downstream is vacuous, and vacuous must report
    CANNOT DETERMINE rather than pass.
    """
    if response is None:
        return "no response object, so the served policy is unknown"
    try:
        header = response.header_value("content-security-policy")
    except Exception as exc:  # noqa: BLE001
        return "could not read the response headers: %s" % exc
    if not header:
        return ("the harness response carried NO Content-Security-Policy, so "
                "no CSP-dependent defect could have been detected here")
    if "script-src" not in header:
        return "the served policy has no script-src directive: %s" % header
    return None
