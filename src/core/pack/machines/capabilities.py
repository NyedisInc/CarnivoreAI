
from __future__ import annotations

from typing import List, Set

CAP_MACHINE = "pack.machine"
CAP_RESERVE = "pack.reserve"
CAP_RESTRICTIONS = "pack.restrictions"
CAP_SKILLS_REF = "pack.skills.ref"
CAP_SKILLS_TAKE = "pack.skills.take"
CAP_SKILLS = "pack.skills"
CAP_SETTINGS_SIGNED = "pack.settings_signed"
CAP_PIPELINE_ROLLUP = "pack.pipeline_rollup"
CAP_TASK_MANAGER_NAMES = "task_manager.names"

_registered: Set[str] = set()


def register(*names: str) -> None:
    _registered.update(n for n in names if isinstance(n, str) and n)


def names() -> List[str]:
    return sorted(_registered)


def has(peer_capabilities, name: str) -> bool:
    return isinstance(peer_capabilities, (list, tuple, set, frozenset)) and name in peer_capabilities
