
from __future__ import annotations

from typing import Any, FrozenSet, Tuple

from src.cplugs.host.sidecar_manifest import TRUST_UNRESTRICTED
from src.cplugs.host.sidecar_registry import SidecarDefinition
from src.cplugs.runtime.dispatch import PluginContext
from src.cplugs.runtime.process import PluginSpec

CAPABILITIES = frozenset({"tools", "events"})


def entry_module(entry: str) -> str:
    return entry[:-3].replace("/", ".")


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
                        manifest_tools=tuple(m.tools), topics=frozenset(m.topics), tier=m.tier)
    return PluginSpec(ctx=ctx, code_dir=d.code_root, entry=entry_module(m.entry), settings=dict(settings or {}), capabilities=CAPABILITIES,
                      subscriptions=frozenset(m.subscriptions), code_digest=m.code_digest, catalog_id=d.item_id, version=m.version,
                      unrestricted=unrestricted, trust_refusal=refusal, consent_owed=consent_owed)
