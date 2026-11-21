from __future__ import annotations

from typing import Any, Dict, Tuple

KINDS_WITH_PROJECT_ID = frozenset({"swarm_card", "session_message", "command"})


def repoint_target(target: Dict[str, Any], source_id: int, target_id: int) -> Tuple[Dict[str, Any], bool]:
    if target.get("kind") == "sequence":
        steps = [repoint_target(step, source_id, target_id) for step in target.get("steps") or ()]
        return {**target, "steps": [step for step, _ in steps]}, any(changed for _, changed in steps)
    if target.get("kind") in KINDS_WITH_PROJECT_ID and target.get("project_id") == source_id:
        return {**target, "project_id": target_id}, True
    return target, False
