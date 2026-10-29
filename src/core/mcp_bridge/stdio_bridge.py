
from __future__ import annotations

import copy
import http.client
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

URL_ENV = "CARNIVORE_MCP_URL"
TOKEN_ENV = "CLOUDECODE_HOOK_TOKEN"
SESSION_ENV = "CLOUDECODE_SESSION_ID"
CHANNEL_ENV = "CARNIVORE_MCP_CHANNEL"
WAIT_ENV = "CARNIVORE_MCP_BRIDGE_WAIT_S"
PROBE_ENV = "CARNIVORE_MCP_BRIDGE_PROBE_S"

DEFAULT_WAIT_S = 60.0
DEFAULT_PROBE_S = 12.0
PROBE_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 5.0
REQUEST_TIMEOUT_S = 900.0
STREAM_READ_TIMEOUT_S = 45.0
BACKOFF_FIRST_S = 0.25
BACKOFF_CAP_S = 2.0
MAX_IN_FLIGHT = 64
RETRY_STATUSES = (502, 503, 504)

CHANNEL_HEADER = "X-Carnivore-Channel"
SESSION_HEADER = "X-Carnivore-Session"
MCP_SESSION_HEADER = "Mcp-Session-Id"
PROTOCOL_HEADER = "Mcp-Protocol-Version"

ERROR_CODE = -32000
REINIT_ID = "carnivore-bridge-init"
TOOLS_CHANGED = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}


class NotSent(Exception):
    pass


class Ambiguous(Exception):
    pass


class ChannelsOff(Exception):
    pass


@dataclass(frozen=True)
class Settings:

    host: str
    port: int
    path: str
    token: str
    session_ref: str
    channel: bool
    wait_s: float
    probe_s: float = DEFAULT_PROBE_S

    @staticmethod
    def from_env(env: Mapping[str, str]) -> "Settings":
        url = env.get(URL_ENV, "")
        parts = urlsplit(url)
        if parts.scheme != "http" or not parts.hostname:
            raise ValueError(f"{URL_ENV} must be set to an http URL")
        try:
            wait_s = float(env.get(WAIT_ENV, DEFAULT_WAIT_S))
        except ValueError:
            wait_s = DEFAULT_WAIT_S
        try:
            probe_s = max(0.1, float(env.get(PROBE_ENV, DEFAULT_PROBE_S)))
        except ValueError:
            probe_s = DEFAULT_PROBE_S
        return Settings(
            host=parts.hostname, port=parts.port or 80, path=parts.path or "/mcp",
            token=env.get(TOKEN_ENV, ""), session_ref=env.get(SESSION_ENV, ""),
            channel=env.get(CHANNEL_ENV) == "1", wait_s=wait_s, probe_s=probe_s,
        )


def log(event: str, **fields: Any) -> None:
    sys.stderr.write("carnivore-bridge " + json.dumps({"event": event, **fields}, default=str) + "\n")
    sys.stderr.flush()


class Emitter:

    def __init__(self, out: Any) -> None:
        self._out = out
        self._lock = threading.Lock()

    def emit(self, message: Any) -> None:
        line = json.dumps(message, separators=(",", ":"))
        with self._lock:
            self._out.write(line + "\n")
            self._out.flush()


class SseDecoder:

    def __init__(self) -> None:
        self._data: List[str] = []

    def feed(self, line: str) -> Optional[str]:
        if line == "":
            data, self._data = "\n".join(self._data), []
            return data or None
        if line.startswith("data:"):
            self._data.append(line[5:].lstrip(" "))
        return None


def decode_sse(text: str) -> List[str]:
    decoder = SseDecoder()
    found = [decoder.feed(line) for line in text.replace("\r", "").split("\n")]
    return [d for d in found if d]


def error_reply(msg_id: Any, text: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": ERROR_CODE, "message": text}}


class Upstream:

    def __init__(self, settings: Settings, emitter: Emitter) -> None:
        self.s = settings
        self.emitter = emitter
        self._lock = threading.Lock()
        self.session_id: Optional[str] = None
        self.protocol: Optional[str] = None
        self._init_message: Optional[dict] = None
        self.ready = threading.Event()

    def headers(self, with_session: bool = True) -> Dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.s.token:
            h["Authorization"] = "Bearer " + self.s.token
        if self.s.session_ref:
            h[SESSION_HEADER] = self.s.session_ref
        if self.s.channel:
            h[CHANNEL_HEADER] = "1"
        if with_session and self.session_id:
            h[MCP_SESSION_HEADER] = self.session_id
        if with_session and self.protocol:
            h[PROTOCOL_HEADER] = self.protocol
        return h

    def roundtrip(self, method: str, body: Optional[bytes], headers: Dict[str, str],
                  read_timeout: float) -> Tuple[int, Dict[str, str], bytes]:
        conn = http.client.HTTPConnection(self.s.host, self.s.port, timeout=CONNECT_TIMEOUT_S)
        try:
            try:
                conn.connect()
                conn.sock.settimeout(read_timeout)
                conn.request(method, self.s.path, body=body, headers=headers)
            except OSError as exc:
                raise NotSent(type(exc).__name__) from exc
            try:
                resp = conn.getresponse()
                data = resp.read()
            except (OSError, http.client.HTTPException) as exc:
                raise Ambiguous(type(exc).__name__) from exc
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def _call(self, body: bytes, idempotent: bool, with_session: bool) -> Tuple[int, Dict[str, str], bytes]:
        deadline = time.monotonic() + self.s.wait_s
        delay, attempts = BACKOFF_FIRST_S, 0
        while True:
            attempts += 1
            try:
                status, hdrs, data = self.roundtrip("POST", body, self.headers(with_session), REQUEST_TIMEOUT_S)
                if status not in RETRY_STATUSES:
                    if attempts > 1:
                        log("recovered", attempts=attempts)
                    return status, hdrs, data
                failure: Exception = NotSent(f"HTTP {status}")
            except NotSent as exc:
                failure = exc
            except Ambiguous as exc:
                if not idempotent:
                    raise
                failure = exc
            if time.monotonic() + delay > deadline:
                raise failure
            if attempts == 1:
                log("server_unreachable", reason=str(failure), wait_s=self.s.wait_s)
            time.sleep(delay)
            delay = min(delay * 2, BACKOFF_CAP_S)

    def reinitialize(self) -> bool:
        if self._init_message is None:
            return False
        msg = copy.deepcopy(self._init_message)
        msg["id"] = REINIT_ID
        try:
            status, hdrs, _ = self._call(json.dumps(msg).encode(), True, False)
        except (NotSent, Ambiguous):
            return False
        new_id = hdrs.get(MCP_SESSION_HEADER.lower())
        if status != 200 or not new_id:
            return False
        with self._lock:
            old, self.session_id = self.session_id, new_id
        try:
            self._call(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(), True, True)
        except (NotSent, Ambiguous):
            log("initialized_notice_lost")
        if (old or "").partition(".")[0] != new_id.partition(".")[0]:
            self.emitter.emit(TOOLS_CHANGED)
            log("tools_changed")
        return True

    def forward(self, message: Any) -> None:
        batch = message if isinstance(message, list) else [message]
        methods = [m.get("method") for m in batch if isinstance(m, dict)]
        is_init = "initialize" in methods
        if is_init and isinstance(message, dict):
            self._init_message = copy.deepcopy(message)
        idempotent = "tools/call" not in methods
        body = json.dumps(message).encode()
        try:
            status, hdrs, data = self._call(body, idempotent, not is_init)
            if status == 404 and not is_init and self.reinitialize():
                status, hdrs, data = self._call(body, idempotent, True)
        except NotSent:
            return self._fail(batch, f"carnivore server unreachable for {int(self.s.wait_s)} s")
        except Ambiguous:
            return self._fail(batch, "connection to the carnivore server was lost during the call; "
                                     "the call was not sent again")
        if is_init:
            self._learn_session(hdrs, data)
        self._relay(status, hdrs, data, batch)

    def _learn_session(self, hdrs: Dict[str, str], data: bytes) -> None:
        sid = hdrs.get(MCP_SESSION_HEADER.lower())
        if sid:
            self.session_id = sid
        try:
            result = json.loads(data).get("result", {})
            self.protocol = result.get("protocolVersion") or self.protocol
        except (ValueError, AttributeError):
            log("initialize_reply_unreadable")
        self.ready.set()

    def _relay(self, status: int, hdrs: Dict[str, str], data: bytes, batch: List[Any]) -> None:
        if status == 202 or (status == 200 and not data):
            return
        text = data.decode("utf-8", "replace")
        chunks = decode_sse(text) if "text/event-stream" in hdrs.get("content-type", "") else [text]
        passed = False
        for chunk in chunks:
            try:
                parsed = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(parsed, (dict, list)):
                self.emitter.emit(parsed)
                passed = True
        if not passed:
            self._fail(batch, f"carnivore server answered HTTP {status}")

    def _fail(self, batch: List[Any], text: str) -> None:
        log("call_failed", reason=text)
        for m in batch:
            if isinstance(m, dict) and "id" in m and "method" in m:
                self.emitter.emit(error_reply(m["id"], text))

    def run_stream(self, stop: threading.Event) -> None:
        while not stop.is_set():
            if not self.ready.wait(1.0):
                continue
            try:
                self._stream_once(stop)
            except ChannelsOff:
                return
            except (NotSent, Ambiguous, OSError, http.client.HTTPException) as exc:
                self._stream_backoff(stop, str(exc) or type(exc).__name__)
                continue
            stop.wait(BACKOFF_FIRST_S)

    def run_heartbeat(self, stop: threading.Event) -> None:
        body = json.dumps({"jsonrpc": "2.0", "id": "carnivore-bridge-heartbeat", "method": "ping"}).encode()
        was_down = False
        while not stop.wait(self.s.probe_s):
            if not self.ready.is_set():
                continue
            try:
                status, _, _ = self.roundtrip("POST", body, self.headers(), PROBE_TIMEOUT_S)
            except (NotSent, Ambiguous) as exc:
                if not was_down:
                    log("heartbeat_server_down", reason=str(exc))
                was_down = True
                continue
            if status in RETRY_STATUSES:
                was_down = True
                continue
            if status == 404 or was_down:
                log("heartbeat_reinitialize", after_outage=was_down)
                was_down = not self.reinitialize()

    def _stream_backoff(self, stop: threading.Event, reason: str) -> None:
        log("stream_down", reason=reason)
        stop.wait(BACKOFF_CAP_S)

    def _stream_once(self, stop: threading.Event) -> None:
        conn = http.client.HTTPConnection(self.s.host, self.s.port, timeout=CONNECT_TIMEOUT_S)
        try:
            try:
                conn.connect()
                conn.sock.settimeout(STREAM_READ_TIMEOUT_S)
                h = self.headers()
                h["Accept"] = "text/event-stream"
                conn.request("GET", self.s.path, headers=h)
            except OSError as exc:
                raise NotSent(type(exc).__name__) from exc
            resp = conn.getresponse()
            if resp.status == 405:
                log("stream_not_offered")
                raise ChannelsOff()
            if resp.status != 200:
                raise NotSent(f"stream HTTP {resp.status}")
            log("stream_open")
            self._probe_session()
            decoder = SseDecoder()
            while not stop.is_set():
                raw = resp.readline()
                if not raw:
                    return
                data = decoder.feed(raw.decode("utf-8", "replace").rstrip("\r\n"))
                if data:
                    try:
                        self.emitter.emit(json.loads(data))
                    except ValueError:
                        log("stream_event_unreadable")
        finally:
            conn.close()

    def _probe_session(self) -> None:
        body = json.dumps({"jsonrpc": "2.0", "id": "carnivore-bridge-probe", "method": "ping"}).encode()
        try:
            status, _, _ = self._call(body, True, True)
            if status == 404:
                self.reinitialize()
        except (NotSent, Ambiguous):
            return


def serve(stdin: Any, stdout: Any, env: Mapping[str, str]) -> int:
    try:
        settings = Settings.from_env(env)
    except ValueError as exc:
        log("bad_configuration", reason=str(exc))
        return 2
    emitter = Emitter(stdout)
    upstream = Upstream(settings, emitter)
    stop = threading.Event()
    slots = threading.BoundedSemaphore(MAX_IN_FLIGHT)
    if settings.channel:
        threading.Thread(target=upstream.run_stream, args=(stop,), daemon=True).start()
    threading.Thread(target=upstream.run_heartbeat, args=(stop,), daemon=True).start()

    def work(message: Any) -> None:
        try:
            upstream.forward(message)
        finally:
            slots.release()

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            log("unreadable_input_line")
            continue
        slots.acquire()
        threading.Thread(target=work, args=(message,), daemon=True).start()
    stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(serve(sys.stdin, sys.stdout, os.environ))
