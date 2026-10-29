
from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional, Tuple


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class StubMcpServer:

    def __init__(self, port: int, status: int = 200, session_id: Optional[str] = None) -> None:
        self.port = port
        self.status = status
        self.session_id = session_id
        self.requests: List[Tuple[str, dict]] = []
        self._server: Optional[ThreadingHTTPServer] = None

    def start(self) -> "StubMcpServer":
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                stub.requests.append((self.command, dict(self.headers)))
                self.send_response(stub.status)
                if stub.session_id and self.command == "POST" and 200 <= stub.status < 300:
                    self.send_header("Mcp-Session-Id", stub.session_id)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            do_GET = do_POST = do_DELETE = _answer

            def log_message(self, *args) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"
