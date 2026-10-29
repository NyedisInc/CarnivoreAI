
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

from tests.helpers.scripted_model import anthropic_sse, responses_sse

FALLBACK_TEXT = "rig: ok"


@dataclass
class Step:

    marker: str
    tool: str
    input: Dict[str, Any] = field(default_factory=dict)
    once: bool = True


class ScriptedModel:

    def __init__(self, steps: Optional[List[Step]] = None) -> None:
        self.steps = list(steps or [])
        self.requests: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._fired: set[int] = set()
        self._calls = 0
        self._httpd: Optional[ThreadingHTTPServer] = None

    def start(self) -> "ScriptedModel":
        rig = self

        class Handler(BaseHTTPRequestHandler):

            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                rig._answer(self, self.path.split("?")[0], body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> "ScriptedModel":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    @property
    def url(self) -> str:
        assert self._httpd, "not started"
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def requests_to(self, path: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [r["body"] for r in self.requests if r["path"] == path]

    def _match(self, text: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for i, step in enumerate(self.steps):
                if step.marker in text and not (step.once and i in self._fired):
                    self._fired.add(i)
                    return {"name": step.tool, "input": step.input}
        return None

    def _answer(self, h: BaseHTTPRequestHandler, path: str, body: Dict[str, Any]) -> None:
        with self._lock:
            self.requests.append({"path": path, "body": body})
            self._calls += 1
            call_id = f"toolu_rig{self._calls}"
        if path == "/v1/messages/count_tokens":
            return self._send_json(h, {"input_tokens": 10})
        if path == "/v1/messages":
            tool = self._match(anthropic_sse.latest_user_text(body)) if body.get("tools") else None
            blocks, stop = anthropic_sse.blocks_for(FALLBACK_TEXT, tool, call_id)
            if not body.get("stream"):
                return self._send_json(h, anthropic_sse.message_json(blocks, stop))
            return self._send_sse(h, anthropic_sse.stream(blocks, stop))
        if path == "/v1/responses":
            tool = self._match(responses_sse.latest_user_text(body)) if body.get("tools") else None
            return self._send_sse(h, responses_sse.stream(FALLBACK_TEXT, tool, call_id))
        h.send_error(404)

    @staticmethod
    def _send_json(h: BaseHTTPRequestHandler, obj: Dict[str, Any]) -> None:
        data = json.dumps(obj).encode()
        h.send_response(200)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)

    @staticmethod
    def _send_sse(h: BaseHTTPRequestHandler, frames: Any) -> None:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.send_header("Connection", "close")
        h.end_headers()
        try:
            for frame in frames:
                h.wfile.write(frame)
                h.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        h.close_connection = True
