
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from src.core.subagents.contract import (
    SHAPE_OK,
    SHAPE_UNRECOGNIZED,
    ShapeCheck,
    check_document as _check,
)
from src.core.subagents.shape_alert import register_contract_source

TIMER_CALL_CONTRACT_VERSION: int = 1
TIMER_RESULT_CONTRACT_VERSION: int = 1

MEASURED_AGAINST_CLAUDE_CODE: str = "2.1.92 to 2.1.181"
MEASURED_ON: str = "2026-09-27"

for _kind in ("timer_call", "timer_result"):
    register_contract_source(
        _kind, "src/core/timers/contract.py",
        'docs/session-status.md, section "Timers of a session"',
        MEASURED_AGAINST_CLAUDE_CODE,
    )

TOOL_WAKEUP: str = "ScheduleWakeup"
TOOL_CRON_CREATE: str = "CronCreate"
TOOL_CRON_DELETE: str = "CronDelete"
TIMER_TOOLS: Tuple[str, ...] = (TOOL_WAKEUP, TOOL_CRON_CREATE, TOOL_CRON_DELETE)

FILE_KIND_CALL: str = "timer_call"
FILE_KIND_RESULT: str = "timer_result"

_CALL_REQUIRED: Mapping[str, Mapping[str, Tuple[type, ...]]] = {
    TOOL_WAKEUP: {"delaySeconds": (int,), "prompt": (str,)},
    TOOL_CRON_CREATE: {"cron": (str,), "prompt": (str,)},
    TOOL_CRON_DELETE: {"id": (str,)},
}
_CALL_OPTIONAL: Mapping[str, Mapping[str, Tuple[type, ...]]] = {
    TOOL_WAKEUP: {"reason": (str,), "stop": (bool,)},
    TOOL_CRON_CREATE: {"recurring": (bool,), "durable": (bool,)},
    TOOL_CRON_DELETE: {},
}
_RESULT_REQUIRED: Mapping[str, Mapping[str, Tuple[type, ...]]] = {
    TOOL_WAKEUP: {"scheduledFor": (int,)},
    TOOL_CRON_CREATE: {"id": (str,)},
    TOOL_CRON_DELETE: {"id": (str,)},
}
_RESULT_OPTIONAL: Mapping[str, Mapping[str, Tuple[type, ...]]] = {
    TOOL_WAKEUP: {"clampedDelaySeconds": (int,), "wasClamped": (bool,)},
    TOOL_CRON_CREATE: {"humanSchedule": (str,), "recurring": (bool,), "durable": (bool,)},
    TOOL_CRON_DELETE: {},
}


def check_call(tool: str, document: Any) -> ShapeCheck:
    return _check(document, file_kind=FILE_KIND_CALL,
                  version=TIMER_CALL_CONTRACT_VERSION,
                  required=_CALL_REQUIRED.get(tool, {}),
                  optional=_CALL_OPTIONAL.get(tool, {}),
                  report_unknown=True)


def check_result(tool: str, document: Any) -> ShapeCheck:
    return _check(document, file_kind=FILE_KIND_RESULT,
                  version=TIMER_RESULT_CONTRACT_VERSION,
                  required=_RESULT_REQUIRED.get(tool, {}),
                  optional=_RESULT_OPTIONAL.get(tool, {}),
                  report_unknown=True)


def contract_versions() -> Dict[str, int]:
    return {FILE_KIND_CALL: TIMER_CALL_CONTRACT_VERSION,
            FILE_KIND_RESULT: TIMER_RESULT_CONTRACT_VERSION}


__all__ = [
    "SHAPE_OK", "SHAPE_UNRECOGNIZED", "ShapeCheck", "TIMER_TOOLS",
    "TOOL_WAKEUP", "TOOL_CRON_CREATE", "TOOL_CRON_DELETE",
    "check_call", "check_result", "contract_versions",
]
