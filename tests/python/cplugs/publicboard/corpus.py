
from __future__ import annotations

import base64
import socket
from dataclasses import dataclass
from typing import Callable, FrozenSet, List, Optional

from tests.python.cplugs.publicboard.harness import HOST, LEAK, LOOPBACK, Reply, exchange, request

WS_NONCE = base64.b64encode(b"corpus-nonce-16b").decode()
JSON = (("Content-Type", "application/json"),)
BAD = frozenset({400})
CLOSED_OR_BAD = frozenset({400, None})
NOT_FOUND = frozenset({404})
MISDIRECTED = frozenset({421})
FORBIDDEN = frozenset({403})
REACHED = frozenset({200})


@dataclass(frozen=True)
class Case:

    name: str
    raw: bytes
    allowed: FrozenSet[Optional[int]]
    edge: bool = True
    single: bool = True


def _get(name: str, target: str, allowed: FrozenSet[Optional[int]], **kw: object) -> Case:
    return Case(name, request("GET", target, **kw), allowed)  # type: ignore[arg-type]


def encoding_cases() -> List[Case]:
    targets = {
        "dot-dot-encoded": "/api/%2e%2e/api/board", "dot-dot-encoded-upper": "/api/%2E%2E/api/board", "slash-encoded": "/api%2fboard",
        "slash-encoded-upper": "/api%2Fboard", "backslash-encoded": "/api%5cboard", "nul-encoded": "/api/board%00",
        "newline-encoded": "/api/board%0a", "overlong-utf8-dot": "/%c0%ae%c0%ae/api/board", "fullwidth-slash-encoded": "/api%EF%BC%8Fboard",
        "letter-encoded-reaches-the-route-when-decoded": "/api/%62oard", "double-encoded": "/api/%252e%252e/board", "percent-alone": "/api/board%",
    }
    out = [_get(f"encoding {name}", target, BAD) for name, target in targets.items()]
    raw_fullwidth = b"GET /api\xef\xbc\x8fboard HTTP/1.1\r\nHost: " + HOST.encode() + b"\r\n\r\n"
    out.append(Case("encoding fullwidth slash as raw bytes", raw_fullwidth, CLOSED_OR_BAD, edge=False))
    return out


def path_shape_cases() -> List[Case]:
    bad = {
        "double-slash-prefix": "//api/board", "dot-segment": "/./api/board", "dot-segment-trailing": "/api/board/.", "double-slash-inside": "/api//board",
        "dot-dot-in-frame-path": "/f/../api/board", "dot-dot-plain": "/api/../api/board", "semicolon": "/api/board;x", "semicolon-param": "/api;a=b/board",
        "query": "/api/board?x", "query-key-value": "/api/board?a=1&b=2", "backslash": "/api\\board", "colon": "/api:board", "space-encoded-as-plus": "/api+board",
        "too-long": "/" + "a" * 300, "exactly-too-long": "/" + "a" * 256, "tab": "/api/board\t",
    }
    out = [_get(f"path {name}", target, BAD) for name, target in bad.items() if name != "tab"]
    out.append(Case("path tab in target", b"GET /api/board\t HTTP/1.1\r\nHost: " + HOST.encode() + b"\r\n\r\n", CLOSED_OR_BAD, edge=False))
    miss = {"uppercase": "/API/board", "mixed-case": "/api/Board", "trailing-slash": "/api/board/", "prefix-extension": "/api/boardx",
            "sub-path": "/api/board/x", "root": "/", "empty-segment-name": "/api/", "unknown": "/admin", "main-app-route": "/api/v1/sessions",
            "main-app-login": "/auth/login", "static": "/static/index.html", "mcp": "/mcp", "websocket-path": "/ws/events", "dotfile": "/.env",
            "frame-ticket-path": "/f/abc", "asset-path": "/a/publicboard.js", "the-answers-route-by-get": "/api/answers"}
    out += [_get(f"path miss {name}", target, NOT_FOUND) for name, target in miss.items()]
    return out


def target_form_cases() -> List[Case]:
    return [
        Case("target absolute-form", request("GET", f"http://{HOST}/api/board"), BAD),
        Case("target absolute-form other host", request("GET", "http://evil.example/api/board"), BAD),
        Case("target asterisk", request("OPTIONS", "*"), BAD),
        Case("target authority-form", request("CONNECT", f"{HOST}:443"), CLOSED_OR_BAD, edge=False),
        Case("target no leading slash", request("GET", "api/board"), CLOSED_OR_BAD, edge=False),
    ]


def host_cases() -> List[Case]:
    bad_hosts = {
        "with-port": f"{HOST}:8190", "trailing-dot": f"{HOST}.", "suffix": f"{HOST}.evil.example", "prefix": f"evil.{HOST}", "ip-literal": "127.0.0.1",
        "ip-literal-with-port": "127.0.0.1:8190", "uppercase": HOST.upper(), "empty": "", "other": "evil.example", "list": f"{HOST}, evil.example",
        "localhost": "localhost", "userinfo": f"user@{HOST}", "leading-dot": f".{HOST}", "ipv6-literal": "[::1]",
    }
    out = [_get(f"host {name}", "/api/board", MISDIRECTED, host=value) for name, value in bad_hosts.items()]
    out.append(Case("host missing (http/1.1)", request("GET", "/api/board", host=None), CLOSED_OR_BAD, edge=False))
    out.append(Case("host missing (http/1.0)", request("GET", "/api/board", host=None, version="HTTP/1.0"), MISDIRECTED))
    dup = request("GET", "/api/board", headers=(("Host", HOST),))
    out.append(Case("host duplicated", dup, frozenset({400, 421}), edge=False))
    out.append(Case("host duplicated, second is evil", request("GET", "/api/board", headers=(("Host", "evil.example"),)), frozenset({400, 421}), edge=False))
    return out


def method_cases() -> List[Case]:
    out = [Case(f"method {m} /api/board", request(m, "/api/board"), NOT_FOUND) for m in ("HEAD", "OPTIONS", "TRACE", "PUT", "PATCH", "DELETE", "POST", "get")]
    out += [Case(f"method {m} /api/answers", request(m, "/api/answers"), NOT_FOUND) for m in ("GET", "PUT", "DELETE", "OPTIONS")]
    for header in ("X-HTTP-Method-Override", "X-Method-Override", "X-HTTP-Method", "_method"):
        out.append(Case(f"override {header}: POST on a GET route", request("GET", "/api/board", headers=((header, "POST"),)), REACHED))
        out.append(Case(f"override {header}: GET on a POST", request("POST", "/api/board", headers=((header, "GET"),) + JSON), NOT_FOUND))
    return out


def body_header_cases() -> List[Case]:
    good = request("POST", "/api/answers", headers=JSON + (("Content-Length", "2"),), body=b"{}")
    chunked = request("POST", "/api/answers", headers=JSON + (("Transfer-Encoding", "chunked"),), body=b"2\r\n{}\r\n0\r\n\r\n")
    smuggle = request("POST", "/api/answers", headers=JSON + (("Transfer-Encoding", "chunked"),),
                      body=b"0\r\n\r\n" + request("GET", "/api/board"))
    both = request("POST", "/api/answers", headers=JSON + (("Content-Length", "2"), ("Transfer-Encoding", "chunked")), body=b"{}")
    return [
        Case("post good (control, reaches the handler)", good, REACHED),
        Case("post at the size cap", request("POST", "/api/answers", headers=JSON + (("Content-Length", "65536"),), body=b"x" * 65536), REACHED),
        Case("post one byte over the cap", request("POST", "/api/answers", headers=JSON + (("Content-Length", "65537"),)), frozenset({413})),
        Case("post huge content-length", request("POST", "/api/answers", headers=JSON + (("Content-Length", "99999999999"),)), frozenset({413, 400})),
        Case("post no content-length", request("POST", "/api/answers", headers=JSON), frozenset({411})),
        Case("post chunked", chunked, BAD),
        Case("post chunked with a smuggled second request", smuggle, BAD),
        Case("post content-length and transfer-encoding", both, CLOSED_OR_BAD, edge=False),
        Case("get chunked", request("GET", "/api/board", headers=(("Transfer-Encoding", "chunked"),), body=b"0\r\n\r\n"), BAD),
        Case("get with a body", request("GET", "/api/board", headers=(("Content-Length", "5"),), body=b"hello"), BAD),
        Case("post content-length not a number", request("POST", "/api/answers", headers=JSON + (("Content-Length", "abc"),)), CLOSED_OR_BAD, edge=False),
        Case("post content-length signed", request("POST", "/api/answers", headers=JSON + (("Content-Length", "+2"),), body=b"{}"), CLOSED_OR_BAD, edge=False),
        Case("post content-length twice, different", request("POST", "/api/answers", headers=JSON + (("Content-Length", "2"), ("Content-Length", "3")), body=b"{}"),
             CLOSED_OR_BAD, edge=False),
        Case("post content-type text/plain", request("POST", "/api/answers", headers=(("Content-Type", "text/plain"), ("Content-Length", "2")), body=b"{}"), frozenset({415})),
        Case("post content-type with charset", request("POST", "/api/answers", headers=(("Content-Type", "application/json; charset=utf-8"), ("Content-Length", "2")), body=b"{}"),
             frozenset({415})),
        Case("post content-type other case", request("POST", "/api/answers", headers=(("Content-Type", "Application/JSON"), ("Content-Length", "2")), body=b"{}"), frozenset({415})),
        Case("post content-type form", request("POST", "/api/answers", headers=(("Content-Type", "application/x-www-form-urlencoded"), ("Content-Length", "2")), body=b"{}"),
             frozenset({415})),
        Case("post no content-type", request("POST", "/api/answers", headers=(("Content-Length", "2"),), body=b"{}"), frozenset({415})),
        Case("post content-type twice", request("POST", "/api/answers", headers=JSON + JSON + (("Content-Length", "2"),), body=b"{}"), frozenset({415})),
        Case("oversized header block", request("GET", "/api/board", headers=(("X-Pad", "a" * 20000),)), frozenset({431})),
        Case("many headers", request("GET", "/api/board", headers=tuple((f"X-H{i}", "a" * 200) for i in range(120))), frozenset({431})),
        Case("header block just under the cap (control)", request("GET", "/api/board", headers=(("X-Pad", "a" * 16000),)), REACHED),
    ]


def upgrade_cases() -> List[Case]:
    ws = (("Connection", "Upgrade"), ("Upgrade", "websocket"), ("Sec-WebSocket-Version", "13"), ("Sec-WebSocket-Key", WS_NONCE))
    h2c = (("Connection", "Upgrade, HTTP2-Settings"), ("Upgrade", "h2c"), ("HTTP2-Settings", "AAMAAABkAAQAoAAAAAIAAAAA"))
    out = []
    for path, want in (("/", NOT_FOUND), ("/api/board", REACHED), ("/api/answers", NOT_FOUND), ("/ws/events", NOT_FOUND), ("/nope", NOT_FOUND)):
        out.append(Case(f"websocket upgrade to {path}", request("GET", path, headers=ws), want))
        out.append(Case(f"h2c upgrade to {path}", request("GET", path, headers=h2c), want))
    out.append(Case("h2 prior knowledge preface", b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n", frozenset({400, 421, None}), edge=False))
    return out


def smuggling_cases() -> List[Case]:
    return [
        Case("pipelined good then good", request("GET", "/api/board") + request("GET", "/api/board"), REACHED),
        Case("pipelined refused then good", request("GET", "/admin") + request("GET", "/api/board"), NOT_FOUND),
        Case("pipelined bad host then good", request("GET", "/api/board", host="evil.example") + request("GET", "/api/board"), MISDIRECTED),
        Case("pipelined bad target then good", request("GET", "/%2e%2e/") + request("GET", "/api/board"), BAD),
        Case("headers split by bare newline", b"GET /api/board HTTP/1.1\nHost: " + HOST.encode() + b"\n\n", CLOSED_OR_BAD | REACHED, edge=False),
    ]


def all_cases() -> List[Case]:
    controls = [Case("control: good GET reaches the handler", request("GET", "/api/board"), REACHED)]
    return (controls + encoding_cases() + path_shape_cases() + target_form_cases() + host_cases() + method_cases() + body_header_cases()
            + upgrade_cases() + smuggling_cases())


def untrusted_peer_cases() -> List[Case]:
    spoof = (("X-Forwarded-For", "203.0.113.11"), ("X-Real-IP", "203.0.113.11"), ("Forwarded", "for=203.0.113.11"), ("Via", "1.1 203.0.113.11"))
    return [Case("untrusted peer: perfect GET", request("GET", "/api/board"), FORBIDDEN),
            Case("untrusted peer: perfect POST", request("POST", "/api/answers", headers=JSON + (("Content-Length", "2"),), body=b"{}"), FORBIDDEN),
            Case("untrusted peer: unknown path", request("GET", "/admin"), FORBIDDEN),
            Case("untrusted peer: bad host", request("GET", "/api/board", host="evil.example"), FORBIDDEN),
            Case("untrusted peer: bad target", request("GET", "/%2e%2e"), FORBIDDEN),
            Case("untrusted peer: spoofed forwarding headers", request("GET", "/api/board", headers=spoof), FORBIDDEN)]


def judge(case: Case, reply: Reply) -> List[str]:
    problems: List[str] = []
    if reply.status not in case.allowed:
        problems.append(f"status {reply.status} not in {sorted(case.allowed, key=str)}")
    if reply.status == 101:
        problems.append("a 101 switching protocols was sent")
    for name in reply.headers:
        if name in ("set-cookie", "server") or name.startswith("access-control-"):
            problems.append(f"forbidden response header {name}")
    if case.single and reply.responses > 1:
        problems.append(f"{reply.responses} responses on the wire for one request")
    if case.edge and reply.status is not None and reply.status != 200:
        problems += _edge_refusal_problems(reply)
    if reply.status == 200 and LEAK not in reply.body:
        problems.append("a 200 that did not come from the canary handler")
    return problems


def _edge_refusal_problems(reply: Reply) -> List[str]:
    problems = []
    if reply.body:
        problems.append("refusal body is not empty")
    wanted = {"x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "cross-origin-opener-policy": "same-origin",
              "cross-origin-resource-policy": "same-origin", "cache-control": "no-store", "connection": "close",
              "content-security-policy": "default-src 'none'; frame-ancestors 'none'"}
    for name, value in wanted.items():
        if reply.headers.get(name) != value:
            problems.append(f"header {name} is {reply.headers.get(name)!r}, wanted {value!r}")
    if "permissions-policy" not in reply.headers:
        problems.append("no permissions-policy header")
    return problems


def slow_client_problem(port: int, deadline: float) -> Optional[str]:
    with socket.create_connection((LOOPBACK, port), timeout=deadline + 2) as conn:
        conn.sendall(f"GET /api/board HTTP/1.1\r\nHost: {HOST}\r\nX-Slow: ".encode())
        conn.settimeout(deadline + 2)
        try:
            data = conn.recv(100)
        except socket.timeout:
            return f"still open {deadline + 2:.0f}s after a trickled request head"
        except ConnectionResetError:
            return None
        return None if data == b"" else f"answered a half request with {data[:20]!r}"


def run_corpus(port: int, cases: Optional[List[Case]] = None, send: Callable[[int, bytes], Reply] = exchange,
               slow_deadline: Optional[float] = None) -> List[str]:
    failures: List[str] = []
    not_found_shapes = {}
    for case in cases if cases is not None else all_cases():
        reply = send(port, case.raw)
        failures += [f"{case.name}: {p}" for p in judge(case, reply)]
        if reply.status == 404:
            not_found_shapes.setdefault(reply.signature(), case.name)
    if slow_deadline is not None:
        problem = slow_client_problem(port, slow_deadline)
        if problem:
            failures.append(f"slow client is cut at the deadline: {problem}")
    if len(not_found_shapes) > 1:
        failures.append(f"404 is not uniform: {len(not_found_shapes)} different shapes, e.g. {sorted(not_found_shapes.values())[:3]}")
    return failures
