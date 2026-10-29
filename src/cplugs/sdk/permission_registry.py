
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from src.cplugs.sdk.ai_features import PERMISSION_PREFIX as AI_PREFIX
from src.cplugs.sdk.network import LAN_PREFIX, LAN_WRITE_PREFIX, NETWORK_PREFIX, NETWORK_WRITE_PREFIX

LOW, MEDIUM, HIGH, NEVER = "low", "medium", "high", "never"
RISKS = (LOW, MEDIUM, HIGH, NEVER)

TIER_CORE, TIER_BUILTIN, TIER_DEV, TIER_CATALOG = "core", "builtin", "dev", "catalog"
FIRST_PARTY_TIERS = (TIER_CORE, TIER_BUILTIN, TIER_DEV)
MANIFEST_TIERS = FIRST_PARTY_TIERS
FIRST_PARTY_HOLDERS = (TIER_BUILTIN, TIER_DEV)
ALL_TIERS = (TIER_CORE, TIER_BUILTIN, TIER_DEV, TIER_CATALOG)
SCHEMA_TIERS = (TIER_BUILTIN, TIER_CATALOG, TIER_DEV)


@dataclass(frozen=True)
class Permission:

    name: str
    risk: str
    tiers: Tuple[str, ...] = ALL_TIERS
    consent_key: str = ""
    declarable: bool = False
    default_granted: bool = False
    platform_granted: bool = False

    @property
    def prefixed(self) -> bool:
        return self.name.endswith(":")


def consent_key_for(name: str) -> str:
    return "plugins.page.permission." + name.rstrip(":").replace(".", "_")


def _row(name: str, risk: str, *, tiers: Tuple[str, ...] = ALL_TIERS, declarable: bool = False, default_granted: bool = False,
         platform_granted: bool = False) -> Permission:
    return Permission(name=name, risk=risk, tiers=tiers, consent_key=consent_key_for(name) if declarable else "",
                      declarable=declarable, default_granted=default_granted, platform_granted=platform_granted)


REGISTRY: Tuple[Permission, ...] = (
    _row("sessions.read", LOW, declarable=True, default_granted=True),
    _row("notify", LOW, declarable=True, default_granted=True),
    _row("feed.view: meta", LOW),
    _row("sessions.output", MEDIUM),
    _row("feed.view: scrubbed", MEDIUM),
    _row("sessions.read.remote", MEDIUM),
    _row("ledger.read", MEDIUM),
    _row("mcp.health.read", MEDIUM, declarable=True),
    _row("flow.read", MEDIUM, declarable=True),
    _row("projects.git.read", MEDIUM),
    _row("feed.view: raw", HIGH),
    _row("sessions.message", HIGH, declarable=True),
    _row("sessions.create", HIGH, declarable=True),
    _row("sessions.control", HIGH),
    _row("agent_writes", HIGH, declarable=True),
    _row("agent_tools", HIGH),
    _row("cross_session", HIGH),
    _row("projects.git.snapshot", HIGH),
    _row("exports.write", HIGH),
    _row("swarm", HIGH, tiers=FIRST_PARTY_HOLDERS, declarable=True),
    _row("activity.read", HIGH, tiers=FIRST_PARTY_HOLDERS, declarable=True),
    _row("imports.write", HIGH, tiers=FIRST_PARTY_HOLDERS, declarable=True),
    _row("work", HIGH, tiers=FIRST_PARTY_HOLDERS, declarable=True, platform_granted=True),
    _row(AI_PREFIX, MEDIUM, declarable=True),
    _row(NETWORK_WRITE_PREFIX, MEDIUM, declarable=True),
    _row(NETWORK_PREFIX, MEDIUM, declarable=True),
    _row("hooks.inbound:", MEDIUM),
    _row(LAN_WRITE_PREFIX, HIGH, declarable=True),
    _row(LAN_PREFIX, HIGH, declarable=True),
)

_EXACT: Dict[str, Permission] = {p.name: p for p in REGISTRY if not p.prefixed}
_FAMILIES: Tuple[Permission, ...] = tuple(p for p in REGISTRY if p.prefixed)

DEFAULT_GRANTED = frozenset(p.name for p in REGISTRY if p.default_granted)
PLATFORM_GRANTED = frozenset(p.name for p in REGISTRY if p.platform_granted)
FIRST_PARTY_ONLY = frozenset(p.name for p in REGISTRY if not p.prefixed and p.tiers == FIRST_PARTY_HOLDERS)


def lookup(permission: str) -> Optional[Permission]:
    row = _EXACT.get(permission)
    if row is not None:
        return row
    for family in _FAMILIES:
        if permission.startswith(family.name):
            return family
    return None


def is_declarable(permission: str) -> bool:
    row = lookup(permission)
    return row is not None and row.declarable


def may_ask(permission: str, tier: str) -> bool:
    row = lookup(permission)
    first_party = tier in FIRST_PARTY_TIERS
    if row is None:
        return first_party
    return tier in row.tiers or (not first_party and TIER_CATALOG in row.tiers)


def risk_of(permission: str, tier: str = TIER_BUILTIN) -> str:
    row = lookup(permission)
    if not may_ask(permission, tier):
        return NEVER
    return row.risk if row is not None else HIGH


def tier_may_ask_text(permission: str) -> str:
    row = lookup(permission)
    return " or ".join(row.tiers if row is not None else FIRST_PARTY_TIERS)
