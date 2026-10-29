
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from src.cplugs.sdk import ManifestError
from src.cplugs.sdk import permission_registry as registry
from src.cplugs.sdk.manifest import parse_manifest
from tests.helpers.catalog_text import catalog_text

ROOT = Path(__file__).resolve().parents[3]
BASE = json.loads((ROOT / "src/cplugs/unread/cplug.json").read_text())


def _with(permissions: list, tier: str = "builtin") -> dict:
    raw = copy.deepcopy(BASE)
    raw["tier"] = tier
    raw.pop("default_enabled", None)
    raw["permissions"] = {"app": permissions}
    return raw


def test_row_names_are_unique() -> None:
    names = [p.name for p in registry.REGISTRY]
    assert len(names) == len(set(names))


def test_every_declarable_permission_has_a_consent_sentence_in_the_catalog() -> None:
    catalog = catalog_text()
    for row in registry.REGISTRY:
        if row.declarable:
            assert row.consent_key and f"'{row.consent_key}'" in catalog, f"{row.name}: no catalog sentence at {row.consent_key}"
        else:
            assert row.consent_key == "", f"{row.name}: a reserved row carries no sentence yet"


def test_the_parser_accepts_exactly_the_declarable_rows() -> None:
    for row in registry.REGISTRY:
        sample = row.name + ("example.com" if row.prefixed else "")
        if row.name == "ai_features:" or not row.declarable:
            continue
        tier = "builtin"
        raw = _with([sample], tier)
        if row.name.startswith(("network_hosts", "lan_hosts")):
            continue
        assert parse_manifest(raw).permissions == (sample,)
    for reserved in [r.name for r in registry.REGISTRY if not r.declarable and not r.prefixed]:
        with pytest.raises(ManifestError, match="unknown app permission"):
            parse_manifest(_with([reserved]))
    with pytest.raises(ManifestError, match="unknown app permission"):
        parse_manifest(_with(["root"]))


def test_the_parser_and_risk_agree_about_which_tier_may_ask() -> None:
    for name in ("swarm", "activity.read", "work", "imports.write"):
        assert parse_manifest(_with([name], "builtin")).permissions == (name,)
        assert parse_manifest(_with([name], "dev")).permissions == (name,)
        with pytest.raises(ManifestError, match="plugin only"):
            parse_manifest(_with([name], "core"))
        assert registry.risk_of(name, "builtin") == registry.HIGH == registry.risk_of(name, "dev")
        for third_party in ("catalog", "thirdparty", "core"):
            assert registry.risk_of(name, third_party) == registry.NEVER
    assert registry.risk_of("sessions.message", "catalog") == registry.HIGH


def test_unknown_names_default_deny() -> None:
    assert registry.risk_of("made.up") == registry.HIGH
    assert registry.risk_of("made.up", "catalog") == registry.NEVER
    assert registry.lookup("made.up") is None
    assert registry.lookup("network_hosts.write:a.com").name == "network_hosts.write:"
    assert registry.lookup("network_hosts:a.com").name == "network_hosts:"


def test_default_and_platform_grants_come_from_the_registry_and_match_the_web_store() -> None:
    assert registry.DEFAULT_GRANTED == {"sessions.read", "notify"}
    assert registry.PLATFORM_GRANTED == {"work"}
    web = (ROOT / "web/src/cplugs/host/enablement.svelte.ts").read_text(encoding="utf-8")
    match = re.search(r"const DEFAULT_GRANTED = new Set\(\[([^\]]*)\]\)", web)
    assert match, "the web enablement store lost its DEFAULT_GRANTED set"
    assert set(re.findall(r"'([^']+)'", match.group(1))) == set(registry.DEFAULT_GRANTED)


def test_the_first_party_only_set_is_derived() -> None:
    assert registry.FIRST_PARTY_ONLY == {"swarm", "activity.read", "work", "imports.write"}
