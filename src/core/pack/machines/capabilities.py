
from __future__ import annotations

from typing import List, Set

CAP_MACHINE = "pack.machine"
CAP_RESERVE = "pack.reserve"
CAP_RESTRICTIONS = "pack.restrictions"
CAP_SKILLS_REF = "pack.skills.ref"
CAP_SKILLS_TAKE = "pack.skills.take"
CAP_SKILLS = "pack.skills"
CAP_SETTINGS_SIGNED = "pack.settings_signed"
CAP_ROSTER = "pack.roster_v1"
CAP_PIPELINE_ROLLUP = "pack.pipeline_rollup"
CAP_ROLLUP_RELAY = "pack.rollup_relay"
CAP_ROLLUP_V2 = "pack.rollup_v2"
CAP_TASK_MANAGER_NAMES = "task_manager.names"
CAP_SWARM_ADOPT = "swarm.adopt_body"

MESH_BUILD_ON = True
CAP_MESH = "pack.mesh_v1"
CAP_ROSTER_V2 = "pack.roster_v2"
CAP_CREDENTIALS_MESH = "pack.credentials.mesh_v1"
CAP_JOBS_MESH = "pack.jobs.mesh_v1"

_registered: Set[str] = set()


def register(*names: str) -> None:
    _registered.update(n for n in names if isinstance(n, str) and n)


def mesh_on() -> bool:
    return MESH_BUILD_ON


def names() -> List[str]:
    return sorted(_registered | ({CAP_MESH, CAP_ROSTER_V2, CAP_CREDENTIALS_MESH, CAP_JOBS_MESH} if mesh_on() else set()))


def has(peer_capabilities, name: str) -> bool:
    return isinstance(peer_capabilities, (list, tuple, set, frozenset)) and name in peer_capabilities
