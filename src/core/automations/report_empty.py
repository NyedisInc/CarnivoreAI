
from __future__ import annotations

from typing import Any

ECHO_KEYS = frozenset({"command", "exit_code", "duration_s"})


def _empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return all(_empty_value(v) for v in value)
    if isinstance(value, dict):
        return all(_empty_value(v) for v in value.values())
    return False


def report_is_empty(report: Any) -> bool:
    if isinstance(report, dict):
        report = {k: v for k, v in report.items() if k not in ECHO_KEYS}
    return _empty_value(report)
