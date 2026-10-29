
from __future__ import annotations

import http.server
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pytest

BRIDGE = Path(__file__).resolve().parents[3] / "src" / "core" / "mcp_bridge" / "stdio_bridge.py"
TOKEN = "tok-not-a-real-secret"
FINGERPRINT = "aaaabbbbccccdddd"


class FakeMcp:

    def __init__(self) -> None:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port: int = probe.getsockname()[1]
        probe.close()
        self.fingerprint = FINGERPRINT
        self.requests: List[dict] = []
        self.drop_tool_calls = False
        self.chunked = False
        self.stream_events: "queue.Queue[dict]" = queue.Queue()
        self._server: Optional[http.server.ThreadingHTTPServer] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def start(self) -> None:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:
                return

            def _send(self, status: int, payload: Optional[dict], headers: Optional[Dict[str, str]] = None) -> None:
                data = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if outer.chunked:
                    self.send_header("Transfer-Encoding", "chunked")
                else:
                    self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if outer.chunked:
                    mid = len(data) // 2
                    for part in (data[:mid], data[mid:]):
                        if part:
                            self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")
                else:
                    self.wfile.write(data)

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                outer.requests.append({"body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
                method = body.get("method")
                if method == "tools/call" and outer.drop_tool_calls:
                    self.close_connection = True
                    self.connection.close()
                    return
                if method == "initialize":
                    return self._send(200, {"jsonrpc": "2.0", "id": body["id"], "result": {
                        "protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": True}},
                        "serverInfo": {"name": "carnivore", "version": "1"}}},
                        {"Mcp-Session-Id": f"{outer.fingerprint}.rnd"})
                sid = self.headers.get("Mcp-Session-Id", "")
                if sid.partition(".")[0] != outer.fingerprint:
                    return self._send(404, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "stale"}})
                if "id" not in body:
                    return self._send(202, None)
                self._send(200, {"jsonrpc": "2.0", "id": body["id"], "result": {"echo": method}})

            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                outer.requests.append({"body": "GET", "headers": {k.lower(): v for k, v in self.headers.items()}})
                try:
                    self.wfile.write(b"retry: 1000\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            event = outer.stream_events.get(timeout=0.2)
                        except queue.Empty:
                            continue
                        self.wfile.write(b"event: message\ndata: " + json.dumps(event).encode() + b"\n\n")
                        self.wfile.flush()
                except OSError:
                    return

        class Server(http.server.ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class Bridge:

    def __init__(self, url: str, channel: bool = False, wait_s: float = 30.0, probe_s: Optional[float] = None) -> None:
        env = {"PATH": os.environ.get("PATH", ""), "CARNIVORE_MCP_URL": url, "CLOUDECODE_HOOK_TOKEN": TOKEN,
               "CLOUDECODE_SESSION_ID": "ses_test", "CARNIVORE_MCP_BRIDGE_WAIT_S": str(wait_s)}
        if channel:
            env["CARNIVORE_MCP_CHANNEL"] = "1"
        if probe_s is not None:
            env["CARNIVORE_MCP_BRIDGE_PROBE_S"] = str(probe_s)
        self.proc = subprocess.Popen([sys.executable, str(BRIDGE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env, text=True, bufsize=1)
        self.out: "queue.Queue[dict]" = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            if line.strip():
                self.out.put(json.loads(line))

    def send(self, message: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout: float = 20.0) -> dict:
        return self.out.get(timeout=timeout)

    def handshake(self) -> dict:
        self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        reply = self.recv()
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return reply

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def fake() -> FakeMcp:
    server = FakeMcp()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def bridge_for() -> Callable[..., Bridge]:
    made: List[Bridge] = []

    def make(url: str, **kw) -> Bridge:
        b = Bridge(url, **kw)
        made.append(b)
        return b

    yield make
    for b in made:
        b.close()


def test_proxies_a_session_with_the_pane_credentials(fake, bridge_for) -> None:
    b = bridge_for(fake.url)
    assert b.handshake()["result"]["serverInfo"]["name"] == "carnivore"
    b.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert b.recv() == {"jsonrpc": "2.0", "id": 2, "result": {"echo": "tools/list"}}
    call = [r for r in fake.requests if r["body"] != "GET" and r["body"].get("method") == "tools/list"][0]
    assert call["headers"]["authorization"] == f"Bearer {TOKEN}"
    assert call["headers"]["x-carnivore-session"] == "ses_test"
    assert call["headers"]["mcp-session-id"].startswith(FINGERPRINT)


def test_a_chunked_reply_is_reassembled(fake, bridge_for) -> None:
    fake.chunked = True
    b = bridge_for(fake.url)
    assert b.handshake()["result"]["serverInfo"]["name"] == "carnivore"
    b.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert b.recv() == {"jsonrpc": "2.0", "id": 2, "result": {"echo": "tools/list"}}


def test_ipv6_host_is_bracketed_and_control_characters_are_refused() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("stdio_bridge_under_test", BRIDGE)
    sb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sb)
    srv = socket.socket(socket.AF_INET6)
    srv.bind(("::1", 0))
    srv.listen(1)
    sock, _ = sb.open_request("::1", srv.getsockname()[1], "GET", "/mcp", None, {}, 2.0, 2.0)
    conn, _ = srv.accept()
    conn.settimeout(2.0)
    assert f"Host: [::1]:{srv.getsockname()[1]}\r\n".encode() in conn.recv(4096)
    for s in (sock, conn, srv):
        s.close()
    with pytest.raises(ValueError):
        sb.open_request("127.0.0.1", 1, "GET", "/mcp", None, {"X": "a\r\nb"}, 1.0, 1.0)


def test_a_call_made_while_the_server_is_down_is_answered_when_it_returns(fake, bridge_for) -> None:
    b = bridge_for(fake.url)
    b.handshake()
    fake.stop()
    b.send({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    time.sleep(2.5)
    assert b.out.empty(), "no answer can exist while the server is down"
    fake.start()
    assert b.recv() == {"jsonrpc": "2.0", "id": 7, "result": {"echo": "tools/list"}}
    b.send({"jsonrpc": "2.0", "id": 8, "method": "tools/list"})
    assert b.recv()["id"] == 8


def test_a_server_that_never_returns_gets_a_clean_error_after_the_bound(fake, bridge_for) -> None:
    b = bridge_for(fake.url, wait_s=1.5)
    b.handshake()
    fake.stop()
    b.send({"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
    reply = b.recv()
    assert reply["id"] == 9 and reply["error"]["code"] == -32000 and "unreachable" in reply["error"]["message"]


def test_a_tool_call_cut_mid_flight_is_never_sent_twice(fake, bridge_for) -> None:
    b = bridge_for(fake.url)
    b.handshake()
    fake.drop_tool_calls = True
    b.send({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "session_send_keys"}})
    reply = b.recv()
    assert reply["id"] == 5 and "not sent again" in reply["error"]["message"]
    assert sum(1 for r in fake.requests if r["body"] != "GET" and r["body"].get("method") == "tools/call") == 1


def test_a_stale_session_re_initializes_and_tells_the_client_the_tools_changed(fake, bridge_for) -> None:
    b = bridge_for(fake.url)
    b.handshake()
    fake.fingerprint = "9999888877776666"
    b.send({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    seen = [b.recv(), b.recv()]
    methods = {m.get("method") for m in seen}
    assert "notifications/tools/list_changed" in methods
    assert {"jsonrpc": "2.0", "id": 3, "result": {"echo": "tools/list"}} in seen


def test_the_channel_stream_forwards_events_and_reconnects_after_a_restart(fake, bridge_for) -> None:
    b = bridge_for(fake.url, channel=True)
    b.handshake()
    event = {"jsonrpc": "2.0", "method": "notifications/claude/channel", "params": {"content": "one", "meta": {}}}
    deadline = time.time() + 10
    while not any(r["body"] == "GET" for r in fake.requests) and time.time() < deadline:
        time.sleep(0.1)
    fake.stream_events.put(event)
    assert b.recv() == event
    assert [r for r in fake.requests if r["body"] == "GET"][0]["headers"]["x-carnivore-channel"] == "1"
    fake.stop()
    time.sleep(1.5)
    fake.start()
    deadline = time.time() + 15
    while sum(1 for r in fake.requests if r["body"] == "GET") < 2 and time.time() < deadline:
        time.sleep(0.2)
    event2 = dict(event, params={"content": "two", "meta": {}})
    fake.stream_events.put(event2)
    assert b.recv() == event2


def test_no_secret_rides_on_argv_and_a_missing_url_is_a_clear_exit() -> None:
    proc = subprocess.run([sys.executable, str(BRIDGE)], input="", capture_output=True, text=True,
                          env={"PATH": os.environ.get("PATH", "")}, timeout=20)
    assert proc.returncode == 2 and "CARNIVORE_MCP_URL" in proc.stderr


def _methods(fake: FakeMcp) -> List[str]:
    return [r["body"].get("method") for r in list(fake.requests) if r["body"] != "GET"]


def test_an_idle_bridge_reaches_a_restarted_server_within_one_probe_with_no_tool_call(fake, bridge_for) -> None:
    probe_s = 0.5
    b = bridge_for(fake.url, probe_s=probe_s)
    b.handshake()
    fake.stop()
    time.sleep(probe_s * 3)
    fake.requests.clear()
    started = time.monotonic()
    fake.start()
    deadline = started + probe_s * 4 + 2
    while time.monotonic() < deadline and "initialize" not in _methods(fake):
        time.sleep(0.05)
    seen = _methods(fake)
    assert "initialize" in seen, f"the bridge never re-initialized on its own: {seen}"
    assert "tools/call" not in seen and "tools/list" not in seen
    first = [r for r in fake.requests if r["body"] != "GET"][0]
    assert first["headers"]["authorization"] == f"Bearer {TOKEN}" and first["headers"]["x-carnivore-session"] == "ses_test"


def test_an_idle_bridge_pings_a_healthy_server_every_probe(fake, bridge_for) -> None:
    b = bridge_for(fake.url, probe_s=0.3)
    b.handshake()
    fake.requests.clear()
    time.sleep(1.5)
    assert _methods(fake).count("ping") >= 2


def test_bridge_import_budget() -> None:
    code = ("import sys,importlib.util as u;s=u.spec_from_file_location('b',sys.argv[1]);m=u.module_from_spec(s);"
            "s.loader.exec_module(m);"
            "print(sorted(x for x in ('http.client','email','ssl','dataclasses','inspect','typing') if x in sys.modules))")
    out = subprocess.run([sys.executable, "-S", "-c", code, str(BRIDGE)], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip().splitlines()[-1] == "[]", out.stdout + out.stderr


def test_a_crlf_credential_never_kills_the_stream_request_or_heartbeat_threads(fake) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("stdio_bridge_crlf", BRIDGE)
    sb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sb)
    sb.BACKOFF_CAP_S = 0.1
    out = queue.Queue()

    class Sink:
        def write(self, line): out.put(line)
        def flush(self): pass

    host, port = fake.url.split("//")[1].split("/")[0].split(":")
    st = sb.Settings(host, int(port), "/mcp", "bad\r\ntoken", "", True, 1.0, 0.1)
    up = sb.Upstream(st, sb.Emitter(Sink()))
    stop = threading.Event()
    up.ready.set()
    threads = [threading.Thread(target=f, args=(stop,), daemon=True) for f in (up.run_stream, up.run_heartbeat)]
    for th in threads:
        th.start()
    up.forward({"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
    time.sleep(0.8)
    alive = [th.is_alive() for th in threads]
    stop.set()
    assert alive == [True, True]
    reply = json.loads(out.get_nowait())
    assert reply["id"] == 5 and "refused" in reply["error"]["message"]
