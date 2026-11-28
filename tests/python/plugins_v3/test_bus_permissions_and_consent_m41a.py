
from __future__ import annotations

import copy
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from src.plugins.host import consent, registry_store, sidecar_spec, state as owner_state
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.sdk import ManifestError, permission_registry as registry
from src.plugins.sdk.manifest import load_manifest, parse_manifest
from src.plugins.sdk.manifest_v2 import ManifestV2Error, parse_manifest_v2
from src.plugins.sdk.schema_check import SchemaSet
from tests.helpers.catalog_text import catalog_text

ROOT = Path(__file__).resolve().parents[3]
BASE_V1 = {
    "schema": 1,
    "id": "unread",
    "name_key": "cplug.unread.name",
    "description_key": "cplug.unread.description",
    "version": "1.0.0",
    "icon": "bell",
    "author": "Alex (example-owner)",
    "min_app_version": "1.12.20",
    "tier": "builtin",
    "default_enabled": True,
    "surfaces": {"plugins": ["session-card-action"]},
    "owns": {
        "strings": ["cplug.unread."],
        "tests": ["tests/python/cplugs/unread/"],
        "contributions": ["session.card_action"],
    },
    "settings_schema": {"version": 1, "fields": {}},
}


def _v2_raw(**overrides):
    raw = {
        "schema": 2,
        "id": "busplug",
        "name": "Bus Plugin",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Bus test manifest",
        "author": "Tester",
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
    }
    raw.update(overrides)
    return raw


def test_permission_registry_and_catalog_register_services_and_events() -> None:
    by_name = {row.name: row for row in registry.REGISTRY}
    assert "services:" in by_name
    assert "events:" in by_name
    for fam in ("services:", "events:"):
        row = by_name[fam]
        assert row.prefixed is True
        assert row.risk == registry.MEDIUM
        assert row.tiers == registry.ALL_TIERS
        assert row.declarable is True

    assert registry.consent_key_for("services:") == "plugins.page.permission.services"
    assert registry.consent_key_for("events:") == "plugins.page.permission.events"
    assert registry.lookup("services:issue-tracker@1") == by_name["services:"]
    assert registry.lookup("events:session.started") == by_name["events:"]
    assert registry.DEFAULT_GRANTED == frozenset({"sessions.read", "notify"})
    assert registry.PLATFORM_GRANTED == frozenset({"work"})
    assert registry.FIRST_PARTY_ONLY == frozenset({"swarm", "activity.read", "work", "imports.write"})

    catalog = catalog_text()
    assert "'plugins.page.permission.services'" in catalog
    assert "'plugins.page.permission.events'" in catalog


def test_manifest_v2_normalizes_services_and_events_and_skips_feed_and_webhook_duplicates(tmp_path: Path) -> None:
    m = parse_manifest_v2(
        _v2_raw(
            permissions={
                "read": ["sessions", "feed.meta"],
                "services": ["kv.v1"],
                "events": ["custom.allowed"],
                "app": ["services:search.v1", "events:app.ping"],
            },
            webhooks={"deploy": {"hmac_secret": "HOOK_SEC"}},
            services={
                "provides": [
                    {
                        "name": "busplug.api",
                        "methods": ["lookup"],
                        "schemas": {
                            "lookup": {
                                "type": "object",
                                "required": ["id"],
                                "properties": {"id": {"type": "string"}},
                                "additionalProperties": False,
                            }
                        },
                    }
                ],
                "consumes": ["issue-tracker@1"],
            },
            events={
                "on": ["feed.meta", "webhook.deploy", "session.started"],
                "emit": ["busplug:ready"],
            },
            ui={
                "slots": ["terminal.toolbar"],
                "contribute": {"session.row_actions": [{"id": "act", "label": "Act"}]},
            },
        )
    )

    assert "services:kv.v1" in m.permissions
    assert "services:search.v1" in m.permissions
    assert "services:issue-tracker@1" in m.permissions
    assert "events:custom.allowed" in m.permissions
    assert "events:app.ping" in m.permissions
    assert "events:busplug:ready" in m.permissions
    assert "events:session.started" in m.permissions
    assert "feed.view: meta" in m.permissions
    assert "hooks.inbound:deploy" in m.permissions
    assert "events:feed.meta" not in m.permissions
    assert "events:webhook.deploy" not in m.permissions

    assert m.services_consumes == ("kv.v1", "search.v1", "issue-tracker@1")
    assert m.events_allowed == ("custom.allowed", "app.ping", "busplug:ready", "session.started")
    assert m.ui_slots == ("terminal.toolbar",)
    assert m.ui_contribute == {"session.row_actions": [{"id": "act", "label": "Act"}]}
    assert m.services_provides[0]["schemas"]["lookup"]["required"] == ["id"]

    (tmp_path / "main.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "carnivore.json").write_text(
        json.dumps(
            _v2_raw(
                tier="builtin",
                permissions={"services": ["kv.v1"], "events": ["custom.allowed"]},
                services={"provides": [{"name": "busplug.api", "methods": ["lookup"]}], "consumes": ["issue-tracker@1"]},
                events={"on": ["session.started"], "emit": ["busplug:ready"]},
                ui={"slots": ["terminal.toolbar"], "contribute": {"session.row_actions": [{"id": "act"}]}},
            )
        ),
        encoding="utf-8",
    )
    loaded = load_manifest(str(tmp_path / "__init__.py"))
    assert "services:kv.v1" in loaded.permissions
    assert "services:issue-tracker@1" in loaded.permissions
    assert "events:busplug:ready" in loaded.permissions
    assert "events:session.started" in loaded.permissions
    assert loaded.services_consumes == ("kv.v1", "issue-tracker@1")
    assert loaded.events_emit == ("busplug:ready",)
    assert loaded.ui_slots == ("terminal.toolbar",)
    assert loaded.ui_contribute == {"session.row_actions": [{"id": "act"}]}

    (tmp_path / "carnivore.json").write_text(
        json.dumps(
            _v2_raw(
                services={"provides": [{"name": "busplug.api", "methods": ["lookup"]}], "consumes": ["issue-tracker@1"]},
                events={"on": ["session.started"], "emit": ["busplug:ready"]},
                ui={"slots": ["terminal.toolbar"], "contribute": {"session.row_actions": [{"id": "act"}]}},
            )
        ),
        encoding="utf-8",
    )
    sm = load_sidecar_manifest(tmp_path, "busplug")
    assert sm.ui_slots == ("terminal.toolbar",)
    assert "services" in sidecar_spec.CAPABILITIES


def test_manifest_v2_and_v1_reject_malformed_bus_schemas_slots_and_ids() -> None:
    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(_v2_raw(id="bad_id"))
    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(_v2_raw(id="bad-id"))

    for bad_perm in ("services:", "events:", "services:BAD!", "events:x"):
        with pytest.raises(ManifestV2Error):
            parse_manifest_v2(_v2_raw(permissions={"app": [bad_perm]}))

    with pytest.raises(ManifestV2Error, match="unsupported JSON Schema"):
        parse_manifest_v2(
            _v2_raw(
                services={
                    "provides": [
                        {
                            "name": "svc.v1",
                            "methods": ["ping"],
                            "schemas": {"ping": {"type": "object", "x-unknown-kw": True}},
                        }
                    ]
                }
            )
        )
    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(
            _v2_raw(
                services={
                    "provides": [
                        {"name": "svc.v1", "methods": ["ping"], "schemas": {"missing": {"type": "object"}}}
                    ]
                }
            )
        )

    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(
            _v2_raw(
                services={
                    "provides": [
                        {"name": "svc.v1", "methods": ["ping"]},
                        {"name": "svc.v1", "methods": ["pong"]},
                    ]
                }
            )
        )

    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(_v2_raw(ui={"slots": ["BAD_SLOT"]}))
    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(_v2_raw(ui={"slots": ["dup.slot", "dup.slot"]}))
    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(_v2_raw(ui={"contribute": {"panel": ["not-an-object"]}}))
    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(_v2_raw(ui={"contribute": {"panel": []}}))

    v1_ok = copy.deepcopy(BASE_V1)
    v1_ok["tier"] = "builtin"
    v1_ok.pop("default_enabled", None)
    v1_ok["permissions"] = {"app": ["services:math.v1", "events:demo.ping"]}
    parsed_v1 = parse_manifest(v1_ok)
    assert parsed_v1.services_consumes == ("math.v1",)
    assert parsed_v1.events_allowed == ("demo.ping",)

    for bad_v1 in ("services:", "events:", "services:BAD"):
        v1_bad = copy.deepcopy(v1_ok)
        v1_bad["permissions"] = {"app": [bad_v1]}
        with pytest.raises(ManifestError):
            parse_manifest(v1_bad)


def test_consent_and_state_enforce_services_events_and_ui_slots(tmp_path: Path) -> None:
    plain_v2 = parse_manifest_v2(
        _v2_raw(
            permissions={
                "services": ["math.v1"],
                "events": ["demo.ping"],
                "reasons": {
                    "services:math.v1": "Call math service",
                    "events:demo.ping": "Emit ping events",
                },
            }
        )
    )
    plain_sm = replace(
        load_sidecar_manifest_from_v2(plain_v2, "a" * 64),
    )
    plain_sheet = consent.sheet(plain_sm)
    assert plain_sheet["ui_slots"] == []
    assert plain_sheet["ui_slots_sha"] == consent.grants_sha(())
    assert all(row["needs_tick"] is True and row["risk"] == registry.MEDIUM for row in plain_sheet["permissions"])

    slot_v2 = parse_manifest_v2(
        _v2_raw(
            permissions={
                "services": ["math.v1"],
                "reasons": {
                    "services:math.v1": "Call math service",
                    "ui.slot:session.row_actions": "Add row quick action",
                },
            },
            ui={"contribute": {"session.row_actions": [{"id": "quick", "label": "Quick"}]}},
        )
    )
    slot_sm = load_sidecar_manifest_from_v2(slot_v2, "b" * 64)
    st_default = owner_state.default_state(slot_sm)
    assert st_default.enabled is False
    assert st_default.grants == ()
    assert st_default.ui_slot_grants == ()
    assert owner_state.granted_ui_slots(tmp_path, slot_sm) == ()

    sheet = consent.sheet(slot_sm)
    assert len(sheet["ui_slots"]) == 1
    assert sheet["ui_slots"][0]["slot"] == "session.row_actions"
    assert sheet["ui_slots"][0]["needs_tick"] is True
    assert sheet["ui_slots"][0]["risk"] == registry.MEDIUM

    base_consent = {
        "digest": sheet["digest"],
        "body_sha": sheet["body_sha"],
        "grants_sha": consent.grants_sha(["services:math.v1"]),
        "ui_slots_sha": consent.grants_sha(["session.row_actions"]),
        "ticks": ["services:math.v1"],
    }

    with pytest.raises(consent.ConsentRefused) as exc_tick:
        consent.check(
            slot_sm,
            ["services:math.v1"],
            [],
            {**base_consent, "slot_ticks": []},
            requested_slots=["session.row_actions"],
            current_slots=(),
        )
    assert exc_tick.value.code == "tick_missing"

    with pytest.raises(consent.ConsentRefused) as exc_mismatch:
        consent.check(
            slot_sm,
            ["services:math.v1"],
            [],
            {**base_consent, "ui_slots_sha": consent.grants_sha([]), "slot_ticks": ["session.row_actions"]},
            requested_slots=["session.row_actions"],
            current_slots=(),
        )
    assert exc_mismatch.value.code == "consent_mismatch"

    no_slots_sha = {k: v for k, v in base_consent.items() if k != "ui_slots_sha"}
    with pytest.raises(consent.ConsentRefused) as exc_omitted:
        consent.check(
            slot_sm,
            ["services:math.v1"],
            [],
            {**no_slots_sha, "slot_ticks": ["session.row_actions"]},
            requested_slots=["session.row_actions"],
            current_slots=(),
        )
    assert exc_omitted.value.status == 422
    assert exc_omitted.value.code == "consent_mismatch"

    plain_consent = {
        "digest": plain_sheet["digest"],
        "body_sha": plain_sheet["body_sha"],
        "grants_sha": consent.grants_sha(["services:math.v1"]),
        "ticks": ["services:math.v1"],
    }
    with pytest.raises(consent.ConsentRefused) as exc_empty_omitted:
        consent.check(
            plain_sm,
            ["services:math.v1"],
            [],
            plain_consent,
            requested_slots=[],
            current_slots=(),
        )
    assert exc_empty_omitted.value.code == "consent_mismatch"
    assert consent.check(plain_sm, ["services:math.v1"], [], plain_consent, requested_slots=None, current_slots=()) == ("services:math.v1",)

    with pytest.raises(consent.ConsentRefused) as exc_unknown:
        consent.check(
            slot_sm,
            ["services:math.v1"],
            [],
            {**base_consent, "slot_ticks": ["unknown.slot"]},
            requested_slots=["unknown.slot"],
            current_slots=(),
        )
    assert exc_unknown.value.code == "grant_not_asked"

    ticked = consent.check(
        slot_sm,
        ["services:math.v1"],
        [],
        {**base_consent, "slot_ticks": ["session.row_actions"]},
        requested_slots=["session.row_actions"],
        current_slots=(),
    )
    assert ticked == ("services:math.v1",)

    no_reason_v2 = parse_manifest_v2(
        _v2_raw(
            permissions={"services": ["math.v1"], "reasons": {"services:math.v1": "Call math"}},
            ui={"contribute": {"session.row_actions": [{"id": "quick"}]}},
        )
    )
    no_reason_sm = load_sidecar_manifest_from_v2(no_reason_v2, "c" * 64)
    nr_sheet = consent.sheet(no_reason_sm)
    with pytest.raises(consent.ConsentRefused) as exc_reason:
        consent.check(
            no_reason_sm,
            ["services:math.v1"],
            [],
            {
                "digest": nr_sheet["digest"],
                "body_sha": nr_sheet["body_sha"],
                "grants_sha": consent.grants_sha(["services:math.v1"]),
                "ui_slots_sha": consent.grants_sha(["session.row_actions"]),
                "ticks": ["services:math.v1"],
                "slot_ticks": ["session.row_actions"],
            },
            requested_slots=["session.row_actions"],
            current_slots=(),
        )
    assert exc_reason.value.code == "reason_missing"

    saved = owner_state.update(
        tmp_path,
        slot_sm,
        0,
        lambda st: replace(
            st,
            enabled=True,
            grants=("services:math.v1",),
            digest=slot_sm.code_digest,
            ui_slot_grants=("session.row_actions",),
        ),
    )
    assert saved.ui_slot_grants == ("session.row_actions",)
    assert saved.as_wire()["grants"]["ui_slots"] == ["session.row_actions"]
    assert owner_state.granted_ui_slots(tmp_path, slot_sm) == ("session.row_actions",)

    moved_sm = replace(slot_sm, code_digest="f" * 64)
    assert owner_state.granted_ui_slots(tmp_path, moved_sm) == ()

    raw_doc, status = registry_store.load_registry(tmp_path)
    assert status == registry_store.STATUS_OK and raw_doc is not None
    assert raw_doc["items"]["busplug"]["ui_slot_grants"] == ["session.row_actions"]
    assert owner_state.stored_entry(tmp_path, "busplug")["ui_slot_grants"] == ["session.row_actions"]

    assert owner_state.strip_consent(tmp_path, "busplug") is True
    after = owner_state.get(tmp_path, slot_sm)
    assert after.grants == ()
    assert after.ui_slot_grants == ()
    assert after.digest == ""


def load_sidecar_manifest_from_v2(v2, digest: str):
    from src.plugins.host.plugin_manifest import from_manifest_v2

    return from_manifest_v2(v2, digest)


@pytest.mark.parametrize(
    "bad_schema",
    [
        {"type": "bogus_type"},
        {"type": ["string", "bogus_type"]},
        {"type": []},
        {"type": 123},
        {"type": "object", "properties": {"s": {"type": "string", "pattern": "[unclosed"}}},
        {"type": "object", "patternProperties": {"[unclosed": {"type": "string"}}},
        {"type": "object", "properties": {"s": {"type": "string", "minLength": "not_int"}}},
        {"minLength": -1},
        {"minLength": True},
        {"type": "object", "required": 123},
        {"required": [123]},
        {"type": "object", "properties": {"n": {"type": "number", "minimum": "x"}}},
        {"type": "array", "items": 123},
        {"type": "array", "minItems": "x"},
        {"uniqueItems": "yes"},
        {"allOf": "bad"},
        {"enum": "bad"},
        {"enum": []},
        {"$ref": "../other.json"},
        {"$ref": "#/$defs/missing"},
        {"$defs": {"a": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"},
    ],
)
def test_manifest_v2_rejects_malformed_service_schema_values(bad_schema: dict) -> None:
    with pytest.raises(ManifestV2Error, match="invalid JSON Schema"):
        parse_manifest_v2(
            _v2_raw(
                services={
                    "provides": [
                        {
                            "name": "svc.v1",
                            "methods": ["op"],
                            "schemas": {"op": bad_schema},
                        }
                    ]
                }
            )
        )


def test_manifest_v2_allows_recursive_tree_service_schema() -> None:
    m = parse_manifest_v2(
        _v2_raw(
            services={
                "provides": [
                    {
                        "name": "svc.v1",
                        "methods": ["walk"],
                        "schemas": {
                            "walk": {
                                "$defs": {
                                    "node": {
                                        "type": "object",
                                        "properties": {"next": {"$ref": "#/$defs/node"}},
                                    }
                                },
                                "$ref": "#/$defs/node",
                            }
                        },
                    }
                ]
            }
        )
    )
    assert "$defs" in m.services_provides[0]["schemas"]["walk"]


def test_schema_check_linear_on_24_level_diamond_dag_and_rejects_non_schema_refs() -> None:
    defs = {
        f"d{i}": {"allOf": [{"$ref": f"#/$defs/d{i + 1}"}, {"$ref": f"#/$defs/d{i + 1}"}]}
        for i in range(24)
    }
    defs["d24"] = {"type": "string"}
    dag_schema = {"$defs": defs, "$ref": "#/$defs/d0"}

    sset = SchemaSet({"args": dag_schema})
    t0 = time.monotonic()
    problems = sset.check_schemas(allow_external_refs=False)
    elapsed_check = time.monotonic() - t0
    assert problems == []
    assert elapsed_check < 0.1

    t1 = time.monotonic()
    assert sset.validate("args", "ok") == []
    assert sset.validate("args", 123)
    assert time.monotonic() - t1 < 0.1

    parsed = parse_manifest_v2(
        _v2_raw(services={"provides": [{"name": "svc.v1", "methods": ["op"], "schemas": {"op": dag_schema}}]})
    )
    assert "$defs" in parsed.services_provides[0]["schemas"]["op"]

    bad_targets = [
        {"properties": {"a": {"type": "string"}}, "$ref": "#/properties"},
        {"properties": {"title": {"type": "string"}}, "$ref": "#/properties"},
        {"$defs": {"a": {"type": "string"}}, "$ref": "#/$defs/a/type"},
        {"$defs": {"a": {"required": ["x"]}}, "$ref": "#/$defs/a/required"},
        {"$defs": {"a": {"type": "string"}}, "$ref": "#/$defs"},
        {"allOf": [{"type": "string"}], "$ref": "#/allOf"},
    ]
    for bad in bad_targets:
        assert SchemaSet({"args": bad}).check_schemas(allow_external_refs=False)
        with pytest.raises(ManifestV2Error, match="invalid JSON Schema"):
            parse_manifest_v2(
                _v2_raw(services={"provides": [{"name": "svc.v1", "methods": ["op"], "schemas": {"op": bad}}]})
            )
