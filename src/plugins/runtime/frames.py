
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

MAX_FRAME_BYTES = 1024 * 1024
MAX_CALL_OUTPUT_BYTES = 5 * 1024 * 1024
NOTIFICATIONS_PER_SECOND = 50
REQUESTS_PER_SECOND = 100
MAX_IN_FLIGHT = 32
MAX_NESTING = 32

PERMISSION_DENIED = -32001
NOT_GRANTED = -32002
DIALOG_OPEN = -32003
RATE_LIMITED = -32004
TOO_LARGE = -32005
TIMEOUT = -32006
DISABLED = -32007
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class FrameViolation(Exception):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Frame:

    kind: str
    id: Optional[int]
    method: Optional[str]
    params: Any
    result: Any = None
    error: Optional[Dict[str, Any]] = None


def _no_duplicates(pairs: List[Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise FrameViolation("duplicate_key")
        out[key] = value
    return out


def _depth(value: Any, limit: int = MAX_NESTING) -> bool:
    stack = [(value, 1)]
    while stack:
        item, level = stack.pop()
        if level > limit:
            return False
        if isinstance(item, dict):
            stack.extend((v, level + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, level + 1) for v in item)
    return True


class LineSplitter:

    def __init__(self, limit: int = MAX_FRAME_BYTES) -> None:
        self._limit = limit
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> List[bytes]:
        lines: List[bytes] = []
        self._buf.extend(chunk)
        while True:
            at = self._buf.find(b"\n")
            if at < 0:
                if len(self._buf) > self._limit:
                    raise FrameViolation("frame_too_large", f"no newline within {self._limit} bytes")
                return lines
            if at > self._limit:
                raise FrameViolation("frame_too_large", f"line of {at} bytes")
            line = bytes(self._buf[:at])
            del self._buf[:at + 1]
            if line.strip():
                lines.append(line)


class FrameGuard:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last_request_id = 0
        self._outstanding: Set[int] = set()
        self._window_start = clock()
        self._notifications = 0
        self._requests = 0
        self._in_flight = 0
        self._call_bytes = 0

    def request_done(self) -> None:
        self._in_flight = max(0, self._in_flight - 1)

    def expect_response(self, request_id: int) -> None:
        self._outstanding.add(request_id)

    def forget(self, request_id: int) -> None:
        self._outstanding.discard(request_id)
        if not self._outstanding:
            self._call_bytes = 0

    def _budget(self, size: int) -> None:
        if self._outstanding:
            self._call_bytes += size
            if self._call_bytes > MAX_CALL_OUTPUT_BYTES:
                raise FrameViolation("call_output_exceeded", f"over {MAX_CALL_OUTPUT_BYTES} bytes in one call")

    def _rate_budget(self, request: bool) -> None:
        now = self._clock()
        if now - self._window_start >= 1.0:
            self._window_start, self._notifications, self._requests = now, 0, 0
        if request:
            self._requests += 1
            if self._requests > REQUESTS_PER_SECOND or self._in_flight >= MAX_IN_FLIGHT:
                raise FrameViolation("request_flood", f"over {REQUESTS_PER_SECOND} a second or {MAX_IN_FLIGHT} unanswered")
            self._in_flight += 1
            return
        self._notifications += 1
        if self._notifications > NOTIFICATIONS_PER_SECOND:
            raise FrameViolation("notification_flood", f"over {NOTIFICATIONS_PER_SECOND} a second")

    def parse(self, line: bytes) -> Frame:
        if len(line) > MAX_FRAME_BYTES:
            raise FrameViolation("frame_too_large", f"line of {len(line)} bytes")
        self._budget(len(line) + 1)
        try:
            doc = json.loads(line.decode("utf-8"), object_pairs_hook=_no_duplicates)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise FrameViolation("bad_json", type(exc).__name__) from exc
        if not isinstance(doc, dict) or doc.get("jsonrpc") != "2.0":
            raise FrameViolation("not_jsonrpc")
        if not _depth(doc):
            raise FrameViolation("too_deep")
        has_id = "id" in doc
        rid = doc.get("id")
        if has_id and (not isinstance(rid, int) or isinstance(rid, bool) or rid < 1):
            raise FrameViolation("bad_id")
        method = doc.get("method")
        if method is None:
            return self._response(doc, rid if has_id else None)
        if not isinstance(method, str) or not 1 <= len(method) <= 64:
            raise FrameViolation("bad_method")
        if "result" in doc or "error" in doc:
            raise FrameViolation("not_jsonrpc", "a request carries no result")
        params = doc.get("params", {})
        if not isinstance(params, (dict, list)):
            raise FrameViolation("not_jsonrpc", "params must be structured")
        if not has_id:
            self._rate_budget(False)
            return Frame("notification", None, method, params)
        if rid <= self._last_request_id:
            raise FrameViolation("id_not_increasing", "duplicate or out-of-order request id")
        self._last_request_id = rid
        self._rate_budget(True)
        return Frame("request", rid, method, params)

    def _response(self, doc: Dict[str, Any], rid: Optional[int]) -> Frame:
        if rid is None:
            raise FrameViolation("bad_id", "a response needs an id")
        if ("result" in doc) == ("error" in doc):
            raise FrameViolation("not_jsonrpc", "a response carries exactly one of result and error")
        if rid not in self._outstanding:
            raise FrameViolation("unsolicited_response", "no outstanding host request has this id")
        self._outstanding.discard(rid)
        error = doc.get("error")
        if error is not None and not isinstance(error, dict):
            raise FrameViolation("not_jsonrpc", "error must be an object")
        if not self._outstanding:
            self._call_bytes = 0
        return Frame("response", rid, None, None, doc.get("result"), error)


def encode(message: Dict[str, Any]) -> bytes:
    data = json.dumps({"jsonrpc": "2.0", **message}, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(data) > MAX_FRAME_BYTES:
        raise FrameViolation("frame_too_large", "the host's own frame is over the limit")
    return data + b"\n"


def error_reply(request_id: int, code: int, message: str, data: Optional[Dict[str, Any]] = None) -> bytes:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data:
        err["data"] = data
    return encode({"id": request_id, "error": err})


def result_reply(request_id: int, result: Any) -> bytes:
    return encode({"id": request_id, "result": result})
