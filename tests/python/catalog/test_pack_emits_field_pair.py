
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from src.core.catalog import publish_prepare_kinds as kinds
from src.core.catalog import submission_rules as rules
from src.plugins.host import install_gates
from src.plugins.sdk.manifest_v2 import ManifestV2Error, parse_manifest_v2

ROOT = Path(__file__).resolve().parents[3]
SMOKE = ROOT / "tests" / "fixtures" / "cplugs" / "warezsmoke"

TOML_CLOCK = (
    'schema = 2\n'
    'id = "clock"\n'
    'name = "Clock"\n'
    'version = "1.0.0"\n'
    'kind = "plugin"\n'
    'description = "Tells the time."\n'
    'author = "harbor"\n'
    'license = "MIT"\n'
    'min_app_version = "1.16.2"\n\n'
    '[run]\n'
    'cmd = ["python3", "clock_main.py"]\n'
    'mode = "rpc"\n\n'
    '[permissions]\n'
    'write = ["notify"]\n\n'
    '[permissions.reasons]\n'
    'notify = "tells you once when the hour turns"\n\n'
    '[[mcp.tools]]\n'
    'name = "clock_now"\n'
    'description = "The time."\n'
    'gate = "read"\n'
    'inputSchema = { type = "object", properties = {}, additionalProperties = false }\n'
)


def _v2_source(tmp_path: Path, *, as_json: bool = False) -> Path:
    src = tmp_path / "clock"
    src.mkdir(parents=True)
    if as_json:
        doc = {
            "schema": 2,
            "id": "clock",
            "name": "Clock",
            "version": "1.0.0",
            "kind": "plugin",
            "description": "Tells the time.",
            "author": "harbor",
            "license": "MIT",
            "tier": "local",
            "default_enabled": False,
            "run": {"cmd": ["python3", "clock_main.py"], "mode": "rpc"},
            "permissions": {"write": ["notify"], "reasons": {"notify": "tells you once when the hour turns"}},
            "mcp": {"tools": [{"name": "clock_now", "description": "The time.", "gate": "read", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]},
        }
        (src / "carnivore.json").write_text(json.dumps(doc), encoding="utf-8")
    else:
        (src / "carnivore.toml").write_text(TOML_CLOCK, encoding="utf-8")
    (src / "clock_main.py").write_text('"""clock."""\nfrom cplug_sdk import Plugin\n\nplugin = Plugin()\n', encoding="utf-8")
    (src / "tests").mkdir()
    (src / "tests" / "test_clock.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return src


def test_publish_prepares_v2_toml_without_tests_or_mutating_source(tmp_path: Path) -> None:
    src = _v2_source(tmp_path)
    prepared = kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor")
    assert prepared.refusals == [], [r.detail for r in prepared.refusals]
    members = dict(prepared.members)
    assert set(members) == {"carnivore.toml", "clock_main.py"}
    assert not (src / "cplug.json").exists()
    facts = install_gates.evaluate("harbor/clock", src).facts
    assert facts["id"] == "clock" and [t["name"] for t in facts["tools"]] == ["clock_now"]


def test_publish_normalizes_v2_json_to_catalog_tier_without_mutating_source(tmp_path: Path) -> None:
    src = _v2_source(tmp_path, as_json=True)
    before = (src / "carnivore.json").read_bytes()
    prepared = kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor")
    assert prepared.refusals == [], [r.detail for r in prepared.refusals]
    members = dict(prepared.members)
    emitted = json.loads(members["carnivore.json"])
    assert emitted["tier"] == "catalog" and emitted["default_enabled"] is False
    assert (src / "carnivore.json").read_bytes() == before


def test_publish_normalizes_v2_toml_local_tier_to_catalog_without_mutating_source(tmp_path: Path) -> None:
    src = _v2_source(tmp_path / "src")
    local_toml = 'tier = "local"\ndefault_enabled = true\n' + TOML_CLOCK
    (src / "carnivore.toml").write_text(local_toml, encoding="utf-8")
    before = (src / "carnivore.toml").read_bytes()

    prepared = kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor")
    assert prepared.refusals == [], [r.detail for r in prepared.refusals]
    assert (src / "carnivore.toml").read_bytes() == before

    members = dict(prepared.members)
    assert prepared.total_bytes == sum(len(body) for body in members.values())
    emitted = tomllib.loads(members["carnivore.toml"].decode("utf-8"))
    assert emitted["tier"] == "catalog" and emitted["default_enabled"] is False
    assert emitted["permissions"] == tomllib.loads(TOML_CLOCK)["permissions"]
    assert emitted["mcp"] == tomllib.loads(TOML_CLOCK)["mcp"]

    staged = tmp_path / "staged"
    staged.mkdir()
    for rel, data in prepared.members:
        dest = staged / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    facts = install_gates.evaluate("harbor/clock", staged).facts
    assert facts["id"] == "clock" and [t["name"] for t in facts["tools"]] == ["clock_now"]


def test_v1_cplug_json_and_coexisting_cplug_json_are_refused(tmp_path: Path) -> None:
    v1_copy = tmp_path / "v1"
    v1_copy.mkdir()
    (v1_copy / "cplug.json").write_text(json.dumps({"schema": 1, "id": "warezsmoke", "name": "warez smoke", "version": "1.0.0", "entry": "warezsmoke_main.py", "default_enabled": False}), encoding="utf-8")
    (v1_copy / "carnivore.json").write_text(json.dumps({"kind": "cplug", "id": "harbor/warezsmoke", "name": "warez smoke", "version": "1.0.0", "tier": "catalog", "default_enabled": False}), encoding="utf-8")
    (v1_copy / "warezsmoke_main.py").write_text((SMOKE / "warezsmoke_main.py").read_text(encoding="utf-8"), encoding="utf-8")
    assert kinds.prepare_kind("cplug", str(v1_copy), "1.0.0", "harbor").refusals
    with pytest.raises(install_gates.CplugGateRefusal, match="carnivore.toml"):
        install_gates.evaluate("harbor/warezsmoke", v1_copy)

    both = _v2_source(tmp_path / "both")
    (both / "cplug.json").write_text('{"schema": 1}', encoding="utf-8")
    assert kinds.prepare_kind("cplug", str(both), "1.0.0", "harbor").refusals
    with pytest.raises(install_gates.CplugGateRefusal):
        install_gates.evaluate("harbor/clock", both)


def test_parse_manifest_v2_refuses_unknown_keys() -> None:
    with pytest.raises(ManifestV2Error, match="surprise"):
        parse_manifest_v2({"schema": 2, "id": "clock", "name": "Clock", "version": "1.0.0", "kind": "plugin", "description": "d", "author": "a", "surprise": 1})


def test_toml_inline_rejects_unsupported_value_with_typed_error() -> None:
    assert not issubclass(kinds.TomlEncodeError, ValueError)
    with pytest.raises(kinds.TomlEncodeError, match="unsupported TOML value type"):
        kinds._toml_inline(object())


def test_toml_text_converts_decode_and_roundtrip_errors_to_toml_encode_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_text: str) -> dict:
        raise tomllib.TOMLDecodeError("bad toml")

    monkeypatch.setattr(kinds.tomllib, "loads", _boom)
    with pytest.raises(kinds.TomlEncodeError, match="invalid TOML"):
        kinds._toml_text({"id": "clock"})

    monkeypatch.undo()
    with pytest.raises(kinds.TomlEncodeError, match="round-trip mismatch"):
        kinds._toml_text({"value": float("nan")})


def test_prepare_kind_cplug_converts_toml_encode_error_to_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _v2_source(tmp_path)
    local_toml = 'tier = "local"\ndefault_enabled = true\n' + TOML_CLOCK
    (src / "carnivore.toml").write_text(local_toml, encoding="utf-8")
    before_toml = (src / "carnivore.toml").read_bytes()
    before_main = (src / "clock_main.py").read_bytes()

    def _fail_toml(_value: dict) -> bytes:
        raise kinds.TomlEncodeError("TOML serialization round-trip mismatch")

    monkeypatch.setattr(kinds, "_toml_text", _fail_toml)
    prepared = kinds.prepare_kind("cplug", str(src), "1.0.0", "harbor")

    assert len(prepared.refusals) == 1
    refusal = prepared.refusals[0]
    assert refusal.code == rules.SUBMISSION_INVALID
    assert refusal.path == "carnivore.toml"
    assert "round-trip mismatch" in refusal.detail
    assert dict(prepared.members) == {"carnivore.toml": before_toml, "clock_main.py": before_main}
    assert prepared.total_bytes == len(before_toml) + len(before_main)
