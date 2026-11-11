
from __future__ import annotations

import codecs
from typing import Any, Dict, List, Mapping

import structlog

from src.core.stream_redactor import StreamRedactor, redact_whole

logger = structlog.get_logger()

STDERR_CAP = 64 * 1024
LINE_CAP = 500
STDERR_EVENT = "cplug_stderr"
EVENT_CAP, FIELDS_CAP, KEY_CAP, VALUE_CAP = 64, 10, 32, 200


def redact_text(text: str) -> str:
    return redact_whole(text)


def redact_log_params(params: Mapping[str, Any]) -> tuple[str, Dict[str, str]]:
    event = redact_text(str(params.get("event", "plugin_log")))[:EVENT_CAP]
    fields = params.get("fields") if isinstance(params.get("fields"), dict) else {}
    safe = {redact_text(str(k))[:KEY_CAP]: redact_text(str(v))[:VALUE_CAP] for k, v in list(fields.items())[:FIELDS_CAP]}
    return event, safe


class StderrLog:

    def __init__(self, plugin_id: str) -> None:
        self._plugin_id = plugin_id
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._redactor = StreamRedactor()
        self._taken = 0
        self._pending = ""
        self.kept = bytearray()

    def feed(self, chunk: bytes) -> None:
        room = max(0, STDERR_CAP - self._taken)
        if not room:
            return
        part = chunk[:room]
        self._taken += len(part)
        self._take(self._redactor.feed(self._decoder.decode(part)))

    def close(self) -> None:
        self._take(self._redactor.feed(self._decoder.decode(b"", final=True)) + self._redactor.flush(end=True))
        if self._pending:
            self._emit(self._pending)
            self._pending = ""

    def _take(self, released: str) -> None:
        if not released:
            return
        self.kept.extend(released.encode("utf-8"))
        lines: List[str] = (self._pending + released).split("\n")
        self._pending = lines.pop()
        for line in lines:
            self._emit(line)

    def _emit(self, line: str) -> None:
        text = line.rstrip("\r")
        if text.strip():
            logger.info(STDERR_EVENT, cplug=self._plugin_id, line=text[:LINE_CAP])
