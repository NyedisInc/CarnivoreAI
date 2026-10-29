
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from src.cplugs.sdk.network import LAN_WRITE_PREFIX, NETWORK_WRITE_PREFIX
from src.cplugs.sdk.permission_registry import FIRST_PARTY_TIERS, HIGH, MEDIUM

_READS_TRANSCRIPTS = frozenset({"activity.read", "feed.view: raw", "feed.view: scrubbed", "sessions.output"})
_WRITE_HOST_PREFIXES = (NETWORK_WRITE_PREFIX, LAN_WRITE_PREFIX)


def needs_tick(risk: str) -> bool:
    return risk in (MEDIUM, HIGH)


def needs_consent(tier: str) -> bool:
    return tier not in FIRST_PARTY_TIERS


def warnings_for(permissions: Tuple[str, ...]) -> List[Dict[str, Any]]:
    reads = [p for p in permissions if p in _READS_TRANSCRIPTS]
    out: List[Dict[str, Any]] = []
    for perm in permissions:
        for prefix in _WRITE_HOST_PREFIXES:
            if perm.startswith(prefix):
                host = perm[len(prefix):]
                out.extend({"code": "sends_transcripts", "reads": r, "host": host} for r in reads)
    return out
