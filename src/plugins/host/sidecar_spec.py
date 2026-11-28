
from __future__ import annotations

from pathlib import Path
from typing import Any, FrozenSet, Mapping, Tuple

from src.plugins.sdk.manifest_v2 import TRUST_UNRESTRICTED
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime.dispatch import PluginContext
from src.plugins.runtime.process import PluginSpec

CAPABILITIES = frozenset({"tools", "events", "routes", "timers", "services"})


def picked_folders(settings: Any, manifest: Any = None) -> Tuple[Path, ...]:
    if not isinstance(settings, Mapping):
        return ()
    schema = getattr(manifest, "settings_schema", None)
    fields = schema.get("fields") if isinstance(schema, Mapping) else None
    fields = fields if isinstance(fields, Mapping) else {}
    folder_keys = {"picked_folders", "export_folders"}
    for key, meta in fields.items():
        if isinstance(meta, Mapping) and str(meta.get("type", "")).lower() in ("folder", "directory", "dir", "path"):
            folder_keys.add(str(key))
    seen: dict[Path, None] = {}
    for key in folder_keys:
        if key not in settings:
            continue
        raw = settings.get(key)
        meta = fields.get(key) if isinstance(fields.get(key), Mapping) else {}
        if "default" in meta and raw == meta.get("default"):
            continue
        items = raw if isinstance(raw, (list, tuple)) else ([raw] if isinstance(raw, (str, Path)) else [])
        for item in items:
            text = str(item).strip() if isinstance(item, (str, Path)) else ""
            if text:
                seen[Path(text)] = None
    return tuple(seen)


def entry_module(entry: str) -> str:
    return entry[:-3].replace("/", ".") if entry.endswith(".py") else entry


def pinned_key_matches(key_id: str, pinned_key_id: str) -> bool:
    pinned = pinned_key_id.strip().upper()
    return bool(pinned) and key_id.strip().upper() == pinned


def resolve_trust(d: SidecarDefinition, consented: bool, pinned_key_id: str) -> Tuple[bool, str]:
    if d.manifest.trust != TRUST_UNRESTRICTED:
        return False, ""
    if d.manifest.tier == "local":
        return (True, "") if consented else (False, "consent_required")
    if pinned_key_matches(d.publisher_key_id, pinned_key_id):
        return True, ""
    return False, "untrusted_publisher"


def build_spec(d: SidecarDefinition, grants: FrozenSet[str], settings: Any, consented: bool = False, pinned_key_id: str = "",
               *, consent_owed: bool = False) -> PluginSpec:
    m = d.manifest
    unrestricted, refusal = resolve_trust(d, consented, pinned_key_id)
    ctx = PluginContext(plugin_id=d.id, install_key=d.install_key, data_dir=d.folder, granted=frozenset(grants),
                        manifest_tools=tuple(m.tools), topics=frozenset(m.topics),
                        picked_folders=picked_folders(settings, m), tier=m.tier,
                        services_consumes=tuple(getattr(m, "services_consumes", ()) or ()),
                        events_emit=tuple(getattr(m, "events_emit", ()) or ()))
    return PluginSpec(ctx=ctx, code_dir=d.code_root, entry=entry_module(m.entry), settings=dict(settings or {}), capabilities=CAPABILITIES,
                      subscriptions=frozenset(m.subscriptions), code_digest=m.code_digest, catalog_id=d.item_id, version=m.version,
                      unrestricted=unrestricted, trust_refusal=refusal, consent_owed=consent_owed,
                      timers=dict(getattr(m, "timers", {}) or {}),
                      run_cmd=tuple(getattr(m, "run_cmd", ()) or ()),
                      run_mode=str(getattr(m, "run_mode", "rpc") or "rpc"),
                      tier0=bool(getattr(m, "tier0", False)))
