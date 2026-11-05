from __future__ import annotations

import re
from pathlib import Path

from scripts.lib_csp_static_server import CSPStaticHandler
from src.security_headers import OWN_POLICY_HEADER, build_view_csp

VIEW_PREFIX = "/__plugin-view-fixture__/"
VIEW_DIR = Path(__file__).resolve().parent / "fixtures" / "plugin-view"
VIEW_TYPES = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8"}
_HOST = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$")


class HarnessHandler(CSPStaticHandler):

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0].startswith(VIEW_PREFIX):
            self._send_view(self.path.split("?", 1)[0][len(VIEW_PREFIX):])
            return
        super().do_GET()

    def _send_view(self, name: str) -> None:
        ext = name.rsplit(".", 1)[-1]
        path = VIEW_DIR / name
        host = self.headers.get("Host", "")
        if "/" in name or ext not in VIEW_TYPES or not path.is_file() or not _HOST.match(host):
            self.send_error(404)
            return
        body = path.read_bytes()
        self._headers_already_stamped = True
        self.send_response(200)
        self.send_header("Content-Type", VIEW_TYPES[ext])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", build_view_csp(f"http://{host}{VIEW_PREFIX}"))
        self.send_header(OWN_POLICY_HEADER, "1")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
