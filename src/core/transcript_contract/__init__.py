
from __future__ import annotations

from src.core.transcript_contract.claude_parse import (
    CLAUDE_RECORD_TYPES,
    QUEUE_OPERATIONS,
    SYSTEM_SUBTYPES,
    parse_claude_line,
    parse_claude_obj,
)
from src.core.transcript_contract.codex_parse import parse_codex_line, parse_codex_obj
from src.core.transcript_contract.drift import DriftTally
from src.core.transcript_contract.fields import Finding
from src.core.transcript_contract.lines import RangeLine, RangeParse, parse_range
from src.core.transcript_contract.parsed import ParsedLine, UnknownRecord
from src.core.transcript_contract.stream import (
    attachment_body,
    complete_lines,
    decode_json,
    decode_object,
    LineScan,
    queue_operation,
    tool_result_blocks,
    typed_record,
    user_message,
)

CONTRACT_VERSION: int = 1

MEASURED_ON: str = "2026-09-30"
MEASURED_CLAUDE_CODE: str = "1.0.61 to 2.1.286"
MEASURED_CODEX_CLI: str = "0.115 prereleases"

__all__ = [
    "CLAUDE_RECORD_TYPES", "CONTRACT_VERSION", "DriftTally", "Finding", "MEASURED_CLAUDE_CODE",
    "MEASURED_CODEX_CLI", "MEASURED_ON", "ParsedLine", "QUEUE_OPERATIONS", "RangeLine",
    "RangeParse", "SYSTEM_SUBTYPES", "UnknownRecord", "parse_claude_line", "parse_claude_obj",
    "parse_codex_line", "parse_codex_obj", "parse_range", "complete_lines", "decode_json",
    "decode_object", "LineScan", "typed_record", "attachment_body", "queue_operation",
    "tool_result_blocks", "user_message",
]
