
from __future__ import annotations

from typing import Any, Dict

from src.core.federation import peer_links
from src.core.pack.machines import capabilities as pack_capabilities

CAP_TRUST_CARRY = "pack.trust_carry"
CAP_IMPORTS_CARRY = "pack.imports_carry"


def source_trusted_field(peer_install_id: str, trusted: bool) -> Dict[str, Any]:
    links = peer_links.LINKS
    if not trusted or links is None or not pack_capabilities.has(links.capabilities(peer_install_id), CAP_TRUST_CARRY):
        return {}
    return {"source_trusted": True}


def source_imports_field(peer_install_id: str, ok: bool) -> Dict[str, Any]:
    links = peer_links.LINKS
    if not ok or links is None or not pack_capabilities.has(links.capabilities(peer_install_id), CAP_IMPORTS_CARRY):
        return {}
    return {"source_imports_ok": True}
