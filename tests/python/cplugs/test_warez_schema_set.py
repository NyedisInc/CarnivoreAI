
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.cplugs.sdk.schema_check import SchemaError, SchemaSet
from src.cplugs.sdk.schema_digest import SCHEMA_DIR, SCHEMA_SET_DIGEST, schema_set_digest
from src.cplugs.sdk.sidecar import schemas, validate_document
from tests.python.cplugs.test_extension_schemas import DIGEST, KINDS, good

SET = schemas()


def l2(kind: str, doc: Dict[str, Any]) -> List[str]:
    return SET.validate(f"warez/{kind}.schema.json", doc)


def front(kind: str, **over: Any) -> Dict[str, Any]:
    extra: Dict[str, Any] = {"tier": "catalog", "license": "MIT", "description": "d", "author": "acme"}
    if kind == "cplug":
        extra.update(id="acme/demo", runtime={"kind": "none"}, data=[])
    elif kind == "widget":
        extra.update(id="acme/card", source="catalog", declarative=True, reads=[{"kind": "feed", "ref": "x.y"}], fixtures=["data", "empty"])
    else:
        extra.update(id=f"acme/{kind}x")
    return good(kind, **{**extra, **over})


def test_the_schema_set_digest_is_pinned() -> None:
    assert schema_set_digest() == SCHEMA_SET_DIGEST, "schemas changed: run python3 -m src.cplugs.sdk.schema_digest, update the constant and the catalog repo pin"


def test_the_digest_ignores_notes_and_the_execute_bit_but_not_content(tmp_path: Path) -> None:
    (tmp_path / "warez").mkdir()
    (tmp_path / "item.schema.json").write_text("{}")
    (tmp_path / "warez" / "a.schema.json").write_text("{}")
    base = schema_set_digest(tmp_path)
    (tmp_path / "README.md").write_text("note")
    (tmp_path / "item.schema.json").chmod(0o755)
    assert schema_set_digest(tmp_path) == base
    (tmp_path / "warez" / "a.schema.json").write_text("{ }")
    assert schema_set_digest(tmp_path) != base
    assert len(base) == 64 and SCHEMA_DIR.is_dir()


def test_the_set_is_keyed_by_relative_path_and_l2_reaches_l1() -> None:
    assert {f"warez/{k}.schema.json" for k in KINDS} | {"warez/item.schema.json"} <= set(SET.documents)
    assert SET.check_keywords() == []
    for kind in KINDS:
        assert l2(kind, front(kind)) == [], kind
        assert validate_document(front(kind)) == [], kind


def test_a_ref_that_leaves_the_set_is_refused() -> None:
    with pytest.raises(SchemaError, match="no such schema file"):
        SchemaSet({"warez/x.schema.json": {"$ref": "../../nope.schema.json"}}).validate("warez/x.schema.json", {})


@pytest.mark.parametrize("rng,ok", [(">=1.2.0", True), ("^1.2.3", True), (">=1.0.0 <2.0.0", True), ("*", True), ("~1.2", True), (">=1 || <0", False), ("1.2.0", False), (">=", False)])
def test_l0_1_range_grammar(rng: str, ok: bool) -> None:
    assert (validate_document(good("skill", harnesses=["claude"], requires=[{"id": "x", "kind": "mcp", "range": rng}])) == []) is ok


@pytest.mark.parametrize("version,ok", [("1.0.0", True), ("1.0.0-beta.2", True), ("1.0", True), ("2.1.0rc1", True), ("^1.0.0", False), ("latest", False), (">=1.0.0", False)])
def test_l0_2_and_3_external_code_is_an_array_with_an_exact_runner_version(version: str, ok: bool) -> None:
    entry = {"server": "s", "runner": "uvx", "package": "p", "version": version, "sha256": DIGEST}
    assert (validate_document(good("mod", external_code=[entry])) == []) is ok


def test_l0_2_external_code_is_closed_per_entry_and_off_other_kinds() -> None:
    entry = {"server": "s", "runner": "npx", "package": "p", "version": "1.0.0", "sha256": DIGEST}
    assert validate_document(good("claude-code-plugin", external_code=[entry, {**entry, "server": "t"}])) == []
    assert validate_document(good("claude-code-plugin", external_code=[{**entry, "extra": 1}]))
    assert validate_document(good("skill", harnesses=["claude"], external_code=[entry]))
    assert validate_document(good("claude-code-plugin", external_code=[entry] * 17))


def test_l0_4_to_7_links_keywords_upstream_and_min_harness_version() -> None:
    sk = {"harnesses": ["claude"]}
    assert validate_document(good("skill", **sk, links={"homepage": "https://a.example"}, keywords=["a-b"], upstream={"name": "rea", "url": "https://x.example", "license": "MIT"}, min_harness_version={"claude": ">=2.1.287"})) == []
    assert validate_document(good("skill", **sk, links={"homepage": "http://a.example"}))
    assert validate_document(good("skill", **sk, keywords=["Bad Key"]))
    assert validate_document(good("skill", **sk, keywords=[f"k{i}" for i in range(11)]))
    assert validate_document(good("skill", **sk, upstream={"name": "x"}))
    assert validate_document(good("skill", **sk, min_harness_version="2.1"))
    assert validate_document(good("skill", **sk, min_harness_version={"vim": ">=1"}))


def test_l1_1_and_2_cplug_catalog_id_runtime_and_network_hosts() -> None:
    assert validate_document(good("cplug", tier="catalog", license="MIT", id="acme/demo", runtime={"kind": "process", "language": "python", "entry": "main.py"}, network_hosts=[{"host": "api.x.com", "reason": "r"}])) == []
    assert validate_document(good("cplug", tier="catalog", license="MIT", id="demo"))
    assert validate_document(good("cplug", id="acme/demo"))
    assert validate_document(good("cplug", runtime={"kind": "none"}))
    assert validate_document(good("cplug", tier="catalog", license="MIT", id="acme/demo", runtime={"kind": "inproc"}))


def test_l1_3_catalog_widget_id() -> None:
    assert validate_document(good("widget", tier="catalog", license="MIT", id="acme/card", source="catalog", declarative=True, reads=[{"kind": "feed", "ref": "a.b"}], fixtures=["data", "empty"])) == []
    assert validate_document(good("widget", tier="catalog", license="MIT", id="demo.card", source="catalog", declarative=True, reads=[{"kind": "feed", "ref": "a.b"}], fixtures=["data", "empty"]))
    assert validate_document(good("widget", id="acme/card"))


def test_l1_4_and_5_loadout_members() -> None:
    member = {"id": "nyedis/hello", "version": "1.0.0-rc.1", "digest": DIGEST}
    assert validate_document(good("loadout", members=[{**member, "kind": "skill"}])) == []
    assert validate_document(good("loadout", members=[{**member, "version": "1.0.0.0.0"}]))
    assert validate_document(good("loadout", members=[{**member, "kind": "loadout"}]))


@pytest.mark.parametrize("kind,over", [
    ("skill", {"id": "bare"}), ("skill", {"tier": "dev"}), ("skill", {"description": " "}), ("skill", {"author": " "}),
    ("skill", {"license": "not an spdx"}), ("skill", {"permissions": [{"name": "notify", "reason": " "}]}),
    ("skill", {"requires": [{"id": "x", "kind": "mcp"}]}), ("skill", {"links": {"homepage": "http://x.example"}}),
    ("skill", {"requires_tools": ["9bad"]}), ("theme", {"runs_script": True}),
    ("claude-code-plugin", {"external_code": [{"server": "s", "runner": "npx", "package": "p", "version": "1.0.0"}]}),
])
def test_l2_rules_refuse_what_l1_accepts(kind: str, over: Dict[str, Any]) -> None:
    doc = front(kind, **({"harnesses": ["claude"]} if kind == "skill" else {}), **over)
    assert l2(kind, doc), over
    if not ({"id", "tier", "links", "external_code"} & set(over)):
        assert validate_document(doc) == [] or "license" in over or "permissions" in over, over


def test_l2_cplug_and_widget_rules() -> None:
    no_runtime = front("cplug")
    del no_runtime["runtime"]
    assert l2("cplug", no_runtime)
    assert l2("cplug", front("cplug", runtime={"kind": "process", "language": "python", "entry": "m.py"}))
    assert l2("cplug", front("cplug", runtime={"kind": "process", "language": "python", "entry": "m.py"}, network_hosts=[])) == []
    for over in ({"source": "sideload"}, {"declarative": False}, {"reads": []}, {"fixtures": ["data"]}, {"fixtures": ["empty", "stress"]}, {"fixtures": []}):
        assert l2("widget", front("widget", **over)), over
