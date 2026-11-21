
from __future__ import annotations

from typing import Mapping, Tuple

TASK_MANAGER = "task_manager"
WIDGET_LAB = "widget_lab"
TOOL_FAMILIES: Mapping[str, Tuple[str, ...]] = {TASK_MANAGER: ("huddle", "reviewboard", "tmdevtools"), WIDGET_LAB: ("devwidgetlab",)}


def family_prefix(family: str) -> str:
    if family not in TOOL_FAMILIES:
        raise KeyError(family)
    return f"{family}_"


TASK_MANAGER_PREFIX = family_prefix(TASK_MANAGER)
