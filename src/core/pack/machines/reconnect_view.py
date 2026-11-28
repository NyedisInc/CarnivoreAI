
from __future__ import annotations

from typing import Any, Callable, Container, Dict, Optional

from src.core.pack.machines import capabilities as caps_mod, interim_policy
from src.core.pack.machines.roster_doc import Roster
from src.core.pack.machines.roster_v2 import RosterV2

REASONS = ("off", "no_eligible", "alpha_not_updated", "ok")
_LINK_UP = frozenset({"connected", "stale", "waiting", "older"})


def takeover_available(roster: Optional[Roster], master: str, master_has_roster: bool, takeover_on: bool) -> Dict[str, Any]:
    if not takeover_on:
        reason = "off"
    elif roster is None or not master_has_roster:
        reason = "alpha_not_updated"
    elif not any(interim_policy.eligible(roster, c.install_id) for c in roster.computers if c.install_id != master):
        reason = "no_eligible"
    else:
        reason = "ok"
    return {"ok": reason == "ok", "reason": reason}


def roster_v1_of(capabilities: Any) -> Optional[bool]:
    if not isinstance(capabilities, (list, tuple, set, frozenset)) or not capabilities:
        return None
    return caps_mod.has(capabilities, caps_mod.CAP_ROSTER)


def augment(view: Dict[str, Any], *, roster: Optional[Roster], home_state: interim_policy.HomeState, relayed: Container[str],
            relay_known: Callable[[str], bool], relay_on: bool, takeover_on: bool) -> Dict[str, Any]:
    master = view.get("master_install_id") or ""
    machines = view.get("machines") or []
    for m in machines:
        iid = m["install_id"]
        entry = roster.entry(iid) if roster is not None else None
        has = caps_mod.has(m.get("capabilities"), caps_mod.CAP_ROSTER)
        is_home = roster is not None and roster.home == iid
        eligible = bool(entry is not None and entry.takeover_eligible)
        m["roster_v1"] = roster_v1_of(m.get("capabilities"))
        m["eligible"] = eligible
        m["is_home"] = is_home
        m["rank"] = roster.order().index(iid) if entry is not None and roster is not None else None
        m["can_claim"] = bool(has and entry is not None and (eligible or is_home))
        m["link_path"] = None if m.get("is_self") else (("relay" if iid in relayed else "direct") if m.get("state") in _LINK_UP else "none")
        m["relay_id_known"] = bool(m.get("is_self")) or relay_known(iid)
    master_row = next((m for m in machines if m["install_id"] == master), None)
    view["generation"] = roster.generation if roster is not None else None
    view["roster_issued_at"] = roster.issued_at if roster is not None else None
    view["home_install_id"] = interim_policy.effective_home(roster, home_state)
    view["interim"] = interim_policy.is_interim(master, roster, home_state)
    view["takeover_available"] = takeover_available(roster, master, bool(master_row and master_row["roster_v1"]), takeover_on)
    view["reconnect"] = {"relay_on": relay_on, "takeover_on": takeover_on}
    return view


def link_switches(view: Dict[str, Any], lst: Any) -> Dict[str, Any]:
    for m in view.get("machines") or []:
        entry = lst.entry(m.get("install_id")) if isinstance(lst, RosterV2) else None
        m["link_peers"] = entry.link_peers if entry is not None else None
        m["mesh_capable"] = entry.mesh if entry is not None else None
    return view
