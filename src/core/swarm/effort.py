
from __future__ import annotations

from typing import Optional, Tuple

DEFAULT_EFFORT = "medium"
ALLOWED_EFFORTS = ("medium", "high", "xhigh")
EFFORTS_WITH_REASON = ("high", "xhigh")
RULE = ("Every Swarm agent runs Opus. Task and feature agents default to medium effort, and a parent raises it "
        "with a written reason.")


class EffortRefused(ValueError):
    pass


def resolve(effort: Optional[str], reason: Optional[str]) -> Tuple[str, str]:
    level = (effort or "").strip() or DEFAULT_EFFORT
    why = (reason or "").strip()
    if level not in ALLOWED_EFFORTS:
        raise EffortRefused(f"effort {level!r} is not allowed: use one of {', '.join(ALLOWED_EFFORTS)}. {RULE}")
    if level in EFFORTS_WITH_REASON and not why:
        raise EffortRefused(f"effort {level} needs effort_reason, a written reason. {RULE}")
    return level, why
