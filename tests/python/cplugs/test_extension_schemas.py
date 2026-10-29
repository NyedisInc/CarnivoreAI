
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.cplugs.sdk.schema_check import SchemaError, SchemaSet
from src.cplugs.sdk.sidecar import SCHEMA_DIR, schemas, validate_document

ROOT = Path(__file__).resolve().parents[3]
KINDS = ("cplug", "widget", "theme", "skill", "claude-code-plugin", "mod", "loadout")
DIGEST = "a" * 64

GOOD: Dict[str, Dict[str, Any]] = {
    "cplug": {"id": "demo", "scope": ["global"], "data": []},
    "widget": {"id": "demo.card", "scope": ["global"], "instancing": "singleton", "sizes": ["small"], "source": "builtin", "declarative": False,
               "hosts": ["home"], "reads": [], "fixtures": ["data", "empty"]},
    "theme": {"id": "neon", "scope": ["global"]},
    "skill": {"id": "nyedis/hello", "scope": ["global", "project"], "harnesses": ["claude"]},
    "claude-code-plugin": {"id": "external/rea", "scope": ["global", "project"]},
    "mod": {"id": "nyedis/working-on", "scope": ["global"], "hooks_modules": ["hooks/register.ts"]},
    "loadout": {"id": "nyedis/starter", "scope": ["global"], "members": [{"id": "nyedis/hello", "version": "1.0.0", "digest": DIGEST}]},
}


def good(kind: str, **over: Any) -> Dict[str, Any]:
    base = {"kind": kind, "name": "demo", "version": "1.0.0", "api_version": 1, "min_app_version": "1.12.20", "author": "t", "tier": "builtin"}
    return {**base, **GOOD[kind], **over}


def test_every_kind_has_exactly_one_l1_schema_that_extends_the_base() -> None:
    files = sorted(p.name for p in SCHEMA_DIR.glob("*.schema.json"))
    assert files == sorted(["item.schema.json", *(f"{k}.schema.json" for k in KINDS)])
    item = json.loads((SCHEMA_DIR / "item.schema.json").read_text())
    assert item["properties"]["kind"]["enum"] == list(KINDS)
    assert item["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    for kind in KINDS:
        doc = json.loads((SCHEMA_DIR / f"{kind}.schema.json").read_text())
        assert doc["$schema"] == item["$schema"]
        assert {"$ref": "item.schema.json"} in doc["allOf"], f"{kind} does not extend L0"
        assert doc["unevaluatedProperties"] is False
        assert doc["allOf"][1]["properties"]["kind"] == {"const": kind}


def test_the_schemas_use_only_keywords_the_checker_applies() -> None:
    assert schemas().check_keywords() == []
    with pytest.raises(SchemaError, match="unsupported keyword"):
        SchemaSet({"x.schema.json": {"dependentRequired": {"a": ["b"]}}}).validate("x.schema.json", {})
    assert SchemaSet({"x.schema.json": {"properties": {"a": {"dependentRequired": {}}}}}).check_keywords() == ["x.schema.json/properties/a/dependentRequired"]


@pytest.mark.parametrize("kind", KINDS)
def test_a_minimal_sidecar_of_each_kind_is_valid(kind: str) -> None:
    assert validate_document(good(kind)) == []


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("field", ["name", "version", "api_version", "min_app_version", "author", "tier", "scope", "id"])
def test_a_missing_base_field_is_refused_for_each_kind(kind: str, field: str) -> None:
    doc = good(kind)
    del doc[field]
    assert any(f"'{field}'" in e for e in validate_document(doc))


@pytest.mark.parametrize("kind", KINDS)
def test_an_unknown_field_is_refused_by_the_closed_object(kind: str) -> None:
    assert any("unknown property 'surprise'" in e for e in validate_document(good(kind, surprise=1)))


def test_the_base_rules_hold_in_every_layer() -> None:
    assert validate_document(good("cplug", tier="core"))
    assert validate_document(good("cplug", tier="builtin")) == [] and validate_document(good("cplug", tier="dev")) == []
    assert validate_document(good("cplug", version="1.x"))
    assert validate_document(good("cplug", api_version=0))
    assert validate_document(good("cplug", scope=[]))
    assert validate_document(good("cplug", permissions=[{"name": "notify"}, {"name": "notify"}]))
    assert validate_document({"kind": "nope"}) == ["$.kind: 'nope' is not a kind of the contract"]
    assert validate_document([]) == ["$: a sidecar must be an object"]


def test_a_catalog_item_needs_a_license_and_a_reason_for_every_permission() -> None:
    catalog = good("skill", tier="catalog")
    assert any("'license'" in e for e in validate_document(catalog))
    catalog = good("skill", tier="catalog", license="MIT", permissions=[{"name": "notify"}])
    assert any("'reason'" in e for e in validate_document(catalog))
    catalog["permissions"][0]["reason"] = "tells you a run finished"
    assert validate_document(catalog) == []
    assert validate_document(good("skill", permissions=[{"name": "notify"}])) == []


def test_each_kind_adds_its_own_rule_on_top_of_the_base() -> None:
    assert validate_document(good("cplug", id="Demo"))
    assert validate_document(good("cplug", scope=["project"]))
    assert validate_document(good("cplug", owns={"routes": ["/x"], "wat": ["y"]}))
    assert validate_document(good("widget", id="demo"))
    assert validate_document(good("widget", sizes=[]))
    assert validate_document(good("skill", harnesses=["vim"]))
    assert validate_document(good("mod", hooks_modules=[]))
    assert validate_document(good("loadout", members=[]))
    assert validate_document(good("loadout", members=[{"id": "nyedis/hello", "version": "1.0.0", "digest": "short"}]))
    code = {"server": "rea", "runner": "npx", "package": "rea-agents", "version": "6.5.0", "sha256": DIGEST}
    assert validate_document(good("claude-code-plugin", external_code=[code])) == []
    assert validate_document(good("claude-code-plugin", external_code=[{**code, "version": "latest"}]))
    assert validate_document(good("claude-code-plugin", external_code=[{k: v for k, v in code.items() if k != "sha256"}]))
    assert validate_document(good("claude-code-plugin", external_code=code))


def test_requirements_name_a_kind() -> None:
    assert validate_document(good("cplug", requires=[{"id": "huddle", "kind": "cplug"}, {"id": "pipeline", "kind": "core"}])) == []
    assert validate_document(good("cplug", requires=[{"id": "huddle", "kind": "mcp"}]))
    assert validate_document(good("skill", requires=[{"id": "rea", "kind": "mcp", "range": ">=6.5.0"}])) == []
    assert validate_document(good("skill", requires=[{"id": "rea"}]))


NATIVE_GAPS = {
    "skill": {"version", "author"},
    "theme": set(),
    "mod": {"author_is_an_object"},
    "plugin": {"author_is_an_object"},
}


def _front_matter(text: str) -> Dict[str, str]:
    lines = text.split("\n")
    if lines[0] != "---":
        return {}
    out: Dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            break
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _overlap(kind: str, files: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "skill":
        fm = _front_matter(files["SKILL.md"]["text"])
        return {"id": fm["name"], "name": fm["name"], "description": fm["description"]}
    if kind == "theme":
        raw = json.loads(files["theme.json"]["text"])
        return {k: raw[k] for k in ("id", "name", "description", "author", "version") if k in raw}
    raw = json.loads(files[".claude-plugin/plugin.json"]["text"])
    author = raw.get("author")
    if kind == "mod":
        modules = json.loads(files["hooks/hooks.json"]["text"])["modules"]
        return {"id": f"tester/{raw['name']}", "name": raw["name"], "description": raw["description"], "version": raw["version"],
                "author": author["name"] if isinstance(author, dict) else author, "hooks_modules": modules}
    return {"id": f"tester/{raw['name']}", "name": raw["name"], "description": raw["description"], "version": raw["version"],
            "author": author["name"] if isinstance(author, dict) else author}


def _sidecar_for(kind: str, overlap: Dict[str, Any]) -> Dict[str, Any]:
    l1 = {"skill": "skill", "theme": "theme", "plugin": "claude-code-plugin", "mod": "mod"}[kind]
    base = {"kind": l1, "version": "1.0.0", "author": "tester", "api_version": 1, "min_app_version": "1.12.20", "tier": "catalog",
            "scope": ["global"], "license": "MIT"}
    if l1 == "skill":
        base["harnesses"] = ["claude"]
        overlap = {**overlap, "id": f"tester/{overlap['id']}"}
    return {**base, **overlap}


def _valid_vectors() -> List[Dict[str, Any]]:
    vectors = json.loads((ROOT / "tests/fixtures/kind_vectors.json").read_text())["vectors"]
    return [v for v in vectors if v["expect"].get("status") == 200]


def test_every_accepted_catalog_vector_validates_as_a_sidecar_of_its_kind() -> None:
    vectors = _valid_vectors()
    assert {v["expect"]["kind"] for v in vectors} == {"skill", "theme", "plugin", "mod"}, "the vectors lost a kind or gained one: extend this test"
    mismatches: List[str] = []
    for v in vectors:
        kind = v["expect"]["kind"]
        doc = _sidecar_for(kind, _overlap(kind, v["files"]))
        errors = validate_document(doc)
        mismatches.extend(f"{v['id']}: {e}" for e in errors)
    assert mismatches == [], "the schema disagrees with a vector the hosted validators accept:\n" + "\n".join(mismatches)


def test_the_vectors_the_hosted_validators_refuse_for_a_bad_name_are_not_silently_expressible() -> None:
    vector = _valid_vectors()[0]
    doc = _sidecar_for("skill", _overlap("skill", vector["files"]))
    doc["id"] = "tester/Hello There"
    assert validate_document(doc)


def test_the_native_gaps_are_the_only_fields_a_sidecar_must_add() -> None:
    skill = next(v for v in _valid_vectors() if v["expect"]["kind"] == "skill")
    native = _overlap("skill", skill["files"])
    assert not NATIVE_GAPS["skill"] & set(native)
    assert NATIVE_GAPS["theme"] == set() and set(_overlap("theme", next(v for v in _valid_vectors() if v["expect"]["kind"] == "theme")["files"])) >= {"version", "author"}
