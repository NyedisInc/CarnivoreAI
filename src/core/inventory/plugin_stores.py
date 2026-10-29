
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.core.inventory.locations import Locations

PLUGINS_DIR = "cplugs"


@dataclass(frozen=True)
class PluginStore:

    plugin_id: str
    decl: Any
    location: Optional[Path]
    setting: str = ""
    enabled: bool = True
    defaulted: bool = False

    @property
    def key(self) -> str:
        return self.decl.full_id(self.plugin_id)

    def policy_json(self) -> Dict[str, str]:
        pol = self.decl.policy
        return {"own": pol.own, "share": pol.share, "reason": pol.reason}


def manifests_of(locations: Locations) -> List[Any]:
    if locations.plugin_manifests is not None:
        return list(locations.plugin_manifests)
    from src.cplugs.registry import CPLUGS  # noqa: PLC0415

    return [d.manifest for d in CPLUGS]


def settings_of(locations: Locations, manifest: Any) -> Dict[str, Any]:
    if locations.plugin_settings is not None:
        return dict(locations.plugin_settings.get(manifest.id, {}))
    from src.cplugs.host import state as owner_state  # noqa: PLC0415

    return dict(owner_state.get(Path(locations.state_dir), manifest).settings)


def enabled_of(locations: Locations, manifest: Any) -> bool:
    if locations.plugin_enabled is not None:
        return bool(locations.plugin_enabled.get(manifest.id, False))
    from src.cplugs.host import state as owner_state  # noqa: PLC0415

    return owner_state.get(Path(locations.state_dir), manifest).enabled


def _setting_text(settings: Mapping[str, Any], fields: Mapping[str, Any], name: str) -> str:
    spec = fields.get(name)
    value = settings.get(name, spec.get("default", "") if isinstance(spec, Mapping) else "")
    return value.strip() if isinstance(value, str) else ""


def _sub_ok(sub: str) -> bool:
    return not sub or (not sub.startswith("/") and ".." not in sub.split("/"))


def locate(manifest: Any, decl: Any, settings: Mapping[str, Any], state_dir: Path) -> PluginStore:
    state = Path(state_dir)
    if decl.state_path:
        return PluginStore(manifest.id, decl, state / decl.state_path)
    if decl.path:
        return PluginStore(manifest.id, decl, state / PLUGINS_DIR / manifest.id / decl.path)
    fields = manifest.settings_schema.get("fields", {}) if isinstance(manifest.settings_schema, Mapping) else {}
    text = _setting_text(settings, fields, decl.root_setting)
    from src.cplugs.sdk.data_decl import default_store_root, is_default_value  # noqa: PLC0415
    if (not text or is_default_value(state, decl.default, text, decl.sub)) and decl.default and _sub_ok(decl.sub):
        return PluginStore(manifest.id, decl, default_store_root(state, decl.default, decl.sub), defaulted=True)
    if not text or not Path(text).expanduser().is_absolute() or not _sub_ok(decl.sub):
        return PluginStore(manifest.id, decl, None, setting=decl.root_setting)
    root = Path(text).expanduser()
    return PluginStore(manifest.id, decl, root / decl.sub if decl.sub else root)


def declared_stores(locations: Locations) -> List[PluginStore]:
    out: List[PluginStore] = []
    for manifest in manifests_of(locations):
        if manifest.data is None:
            continue
        settings = settings_of(locations, manifest)
        on = enabled_of(locations, manifest)
        out += [replace(locate(manifest, decl, settings, Path(locations.state_dir)), enabled=on) for decl in manifest.data]
    return out


def backup_provider(locations: Locations) -> Optional[PluginStore]:
    from src.cplugs.sdk.data_decl import PROVIDES_BACKUP_POINTS  # noqa: PLC0415

    for manifest in manifests_of(locations):
        if manifest.data is None or not enabled_of(locations, manifest):
            continue
        settings = settings_of(locations, manifest)
        for decl in manifest.data:
            if decl.provides == PROVIDES_BACKUP_POINTS:
                return locate(manifest, decl, settings, Path(locations.state_dir))
    return None


def backup_opt_out(locations: Locations) -> frozenset:
    from src.core.backup_health.vault_record import OPT_OUT_SETTING, opt_out_units  # noqa: PLC0415
    from src.cplugs.sdk.data_decl import PROVIDES_BACKUP_POINTS  # noqa: PLC0415

    for manifest in manifests_of(locations):
        if manifest.data and any(decl.provides == PROVIDES_BACKUP_POINTS for decl in manifest.data):
            return opt_out_units(settings_of(locations, manifest).get(OPT_OUT_SETTING))
    return frozenset()


def undeclared_manifests(locations: Locations) -> List[Any]:
    return [m for m in manifests_of(locations) if m.data is None]


def state_rel(store: PluginStore, state_dir: Path) -> Optional[str]:
    if store.location is None:
        return None
    try:
        rel = store.location.relative_to(Path(state_dir)).as_posix()
    except ValueError:
        return None
    return None if rel == "." else rel


def declared_state_rels(locations: Locations) -> List[str]:
    state = Path(locations.state_dir)
    return sorted({rel for rel in (state_rel(s, state) for s in declared_stores(locations)) if rel})


def superseded(pattern: str, rels: Sequence[str]) -> bool:
    return any(rel == pattern or fnmatch(rel, pattern) or rel.startswith(pattern.rstrip("/") + "/") for rel in rels)


def root_problem(store: PluginStore, locations: Locations) -> Optional[str]:
    if store.location is None or store.defaulted:
        return None
    real = os.path.realpath(store.location)
    homes = [*locations.claude_homes(), locations.codex_home(), Path(locations.state_dir)]
    for home in (os.path.realpath(h) for h in homes):
        if real == home or real.startswith(home.rstrip(os.sep) + os.sep) or home.startswith(real.rstrip(os.sep) + os.sep) or real == os.sep:
            return f"{store.key}: {store.location} is inside, or holds, a live harness home or the state folder, so it is not read"
    return None
