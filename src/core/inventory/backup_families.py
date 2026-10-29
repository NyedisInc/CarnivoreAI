
from __future__ import annotations

from typing import Any, Dict, FrozenSet, List

from src.core.inventory import plugin_stores as stores
from src.core.inventory.locations import Locations
from src.core.inventory.model import Inventory

STATE_OK, STATE_PLUGIN_OFF, STATE_SWITCHED_OFF = "ok", "plugin_off", "switched_off"
_INSTALL = "install"
_CARRIED, _VAULT = "carried", "vault"


def _state(enabled: bool, unit: str, switched_off: FrozenSet[str]) -> str:
    if not enabled:
        return STATE_PLUGIN_OFF
    return STATE_SWITCHED_OFF if unit in switched_off else STATE_OK


def backup_families(inv: Inventory, locations: Locations) -> List[Dict[str, Any]]:
    names = {m.id: m.name_key for m in stores.manifests_of(locations)}
    switched_off = stores.backup_opt_out(locations)
    out: Dict[str, Dict[str, Any]] = {}
    for art in inv.artifacts:
        loc = art.locator
        plugin, data = loc.get("plugin"), loc.get("data")
        if not plugin or not data or loc.get("backup") != _VAULT or loc.get("decl_kind") != "folder":
            continue
        if loc.get("scope_by") == _INSTALL or (loc.get("policy") or {}).get("own") != _CARRIED or not loc.get("units"):
            continue
        unit = f"{plugin}.{data}"
        out[unit] = {"unit": unit, "plugin": plugin, "data": data, "plugin_name_key": names.get(str(plugin), ""),
                     "scope_by": loc.get("scope_by"), "state": _state(bool(loc.get("enabled", True)), unit, switched_off),
                     "root": loc.get("root"), "units": [dict(u) for u in loc["units"]]}
    return [out[k] for k in sorted(out)]
