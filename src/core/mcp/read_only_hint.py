
from __future__ import annotations

from typing import Any, Optional

NOT_READ_ONLY: dict[str, str] = {
    "crosstalk_inbox": "settles held messages as delivered because their text is in the answer",
    "crosstalk_thread": "settles the caller's held native messages as delivered (the same receipt as the inbox)",
    "crosstalk_wait": "reads through the inbox's store call, which settles held messages as delivered",
    "perf_profile": "runs the CPU sampler for up to 45 seconds",
    "task_manager_tasks_list": "records the read (the item's unread tick) and remembers this pane as the list's latest caller",
    "task_manager_changes": "advances this pane's cursor, records the read and remembers the caller",
    "computers_list": "with detail specs it takes the viewer lease that keeps the Pack's per-agent tick running for two minutes",
    "ai_models_list": "with refresh true it asks the provider and rewrites the model cache",
}

READ_ONLY = {"readOnlyHint": True}


def annotations(name: str, write_tools: frozenset[str]) -> Optional[dict[str, Any]]:
    if name in write_tools or name in NOT_READ_ONLY:
        return None
    return dict(READ_ONLY)
