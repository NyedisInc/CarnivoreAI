
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from src.core.pack.machines.roster_v2 import RosterV2


def known(mem_switches: Mapping[str, bool], mem_at: Mapping[str, int], held: Optional[RosterV2]) -> Dict[str, Tuple[bool, int]]:
    out: Dict[str, Tuple[bool, int]] = {i: (bool(on), int(mem_at.get(i, 0))) for i, on in mem_switches.items()}
    for c in (held.computers if held is not None else []):
        mine = (bool(c.link_peers), int(c.link_at))
        old = out.get(c.install_id)
        if old is None or mine[1] > old[1] or (mine[1] == old[1] and not mine[0]):
            out[c.install_id] = mine
    return out


def older_on(knowledge: Mapping[str, Tuple[bool, int]], new: RosterV2) -> List[str]:
    return [c.install_id for c in new.computers
            if c.link_peers and c.install_id in knowledge and not knowledge[c.install_id][0] and knowledge[c.install_id][1] >= c.link_at]


def join(prior_ok: bool, prior_switches: Mapping[str, bool], prior_at: Mapping[str, int], new: RosterV2) -> Dict[str, Any]:
    switches: Dict[str, bool] = {}
    at: Dict[str, int] = {}
    for c in new.computers:
        on, stamp = bool(c.link_peers), int(c.link_at)
        if prior_ok and c.install_id in prior_switches:
            p_on, p_at = bool(prior_switches[c.install_id]), int(prior_at.get(c.install_id, 0))
            if p_at > stamp or (p_at == stamp and not p_on):
                on, stamp = p_on, p_at
        switches[c.install_id], at[c.install_id] = on, stamp
    return {"generation": new.generation, "switches": switches, "at": at}


def stamped(v2: RosterV2, owner_ids: Iterable[str], source: Mapping[str, bool], source_at: Mapping[str, int]) -> RosterV2:
    named = set(owner_ids)
    computers = []
    for c in v2.computers:
        if c.install_id in named:
            stamp = v2.generation
        elif c.install_id in source:
            stamp = int(source_at.get(c.install_id, 0))
        else:
            stamp = c.link_at
        computers.append({**c.model_dump(), "link_at": min(stamp, v2.generation)})
    return RosterV2(**{**v2.model_dump(), "computers": computers})
