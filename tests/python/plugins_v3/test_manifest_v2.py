
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.plugins.host import install_gates, secret_store
from src.plugins.host.install_gates import CplugGateRefusal
from src.plugins.host.plugin_manifest import SidecarManifestError, load_sidecar_manifest
from src.plugins.sdk.manifest import load_manifest
from src.plugins.sdk.manifest_v2 import ManifestV2Error, has_v2_manifest, load_manifest_v2, parse_manifest_v2


def _write_entry(root: Path, rel: str = "main.py") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("from cplug_sdk import Plugin\nplugin = Plugin()\n", encoding="utf-8")


def test_parse_toml_v2_full_manifest(tmp_path: Path) -> None:
    _write_entry(tmp_path)
    (tmp_path / "carnivore.toml").write_text(
        """
schema = 2
id = "pulsemon"
name = "Pulse Monitor"
version = "1.2.3"
kind = "plugin"
description = "Monitors session pulse and triggers webhooks."
author = "Acme"
license = "MIT"
min_app_version = "1.20.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"

[permissions]
read = ["sessions", "sessions.output", "feed.meta", "ledger", "projects.git"]
write = ["notify", "exports", "sessions.control"]
secrets = [{ name = "HOOK_TOKEN", label = "Hook Token", help = "Verify incoming hooks" }]

[[permissions.network]]
host = "api.github.com"
methods = ["GET"]
reason = "Read repo metadata"

[permissions.reasons]
"sessions.read" = "Watch session status"

[timers.heartbeat]
every_seconds = 30

[webhooks.deploy]
hmac_secret = "HOOK_TOKEN"
header = "X-Hub-Signature"

[mcp]
[[mcp.tools]]
name = "pulse_ping"
description = "Check pulse status"
gate = "read"
inputSchema = { type = "object" }

[events]
on = ["feed.meta", "webhook.deploy"]
emit = ["pulse.ready"]

[ui.contribute]
sidebar = [{ label = "Pulse", surface = "tab" }]

[[services.provides]]
name = "pulse.state"
methods = ["get_status"]
""",
        encoding="utf-8",
    )

    assert has_v2_manifest(tmp_path) is True
    m = load_manifest_v2(tmp_path)
    assert m.schema == 2
    assert m.id == "pulsemon"
    assert m.tier0 is False
    assert m.run_cmd == ("python3", "main.py")
    assert m.entry == "main.py"
    assert m.timers == {"heartbeat": 30}
    assert m.webhooks == {"deploy": {"hmac_secret": "HOOK_TOKEN", "header": "X-Hub-Signature"}}
    assert m.events_on == ("feed.meta", "webhook.deploy")
    assert m.events_emit == ("pulse.ready",)
    assert "sessions.read" in m.permissions
    assert "sessions.output" in m.permissions
    assert "feed.view: meta" in m.permissions
    assert "ledger.read" in m.permissions
    assert "projects.git.read" in m.permissions
    assert "exports.write" in m.permissions
    assert "sessions.control" in m.permissions
    assert "hooks.inbound:deploy" in m.permissions
    assert "network_hosts:api.github.com" in m.permissions
    assert len(m.tools) == 1 and m.tools[0]["name"] == "pulse_ping"

    sm = load_sidecar_manifest(tmp_path, "pulsemon")
    assert sm.schema_version == 2
    assert sm.timers == {"heartbeat": 30}
    assert sm.webhooks == {"deploy": {"hmac_secret": "HOOK_TOKEN", "header": "X-Hub-Signature"}}
    assert sm.subscriptions == ("feed.meta", "webhook.deploy")


def test_parse_json_v2_and_tier0_without_run(tmp_path: Path) -> None:
    (tmp_path / "carnivore.json").write_text(
        json.dumps({
            "schema": 2,
            "id": "quicktheme",
            "name": "Quick Theme",
            "version": "0.1.0",
            "kind": "theme",
            "description": "Declarative Tier 0 theme",
            "author": "Tester",
            "ui": {"topics": ["status"]},
        }),
        encoding="utf-8",
    )
    m = load_manifest(str(tmp_path / "__init__.py"))
    assert m.schema if hasattr(m, "schema") else True
    assert m.id == "quicktheme"

    sm = load_sidecar_manifest(tmp_path, "quicktheme")
    assert sm.tier0 is True


def test_dual_manifest_ambiguity_rejected(tmp_path: Path) -> None:
    _write_entry(tmp_path)
    (tmp_path / "carnivore.toml").write_text('schema = 2\nid = "dup"\nname = "Dup"\nversion = "1.0.0"\ndescription = "x"\nauthor = "a"\n', encoding="utf-8")
    (tmp_path / "carnivore.json").write_text('{"schema": 2}', encoding="utf-8")
    with pytest.raises(ManifestV2Error, match="both carnivore.toml and carnivore.json"):
        load_manifest_v2(tmp_path)
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(tmp_path, "dup")


def test_install_gates_allows_toml_and_secret_store_binds_webhook(tmp_path: Path) -> None:
    _write_entry(tmp_path)
    (tmp_path / "carnivore.toml").write_text(
        """
schema = 2
id = "hooked"
name = "Hooked"
version = "1.0.0"
kind = "plugin"
description = "Webhook test"
author = "Acme"

[run]
cmd = ["python3", "main.py"]

[permissions]
secrets = [{ name = "SEC", label = "Hook Secret", help = "Webhook HMAC" }]

[webhooks.ci]
hmac_secret = "SEC"
""",
        encoding="utf-8",
    )
    facts = install_gates.evaluate("acme/hooked", tmp_path)
    assert facts.facts["id"] == "hooked"

    sm = load_sidecar_manifest(tmp_path, "hooked")
    mem_kc = {}

    class _FakeKC:
        def read(self, svc, acc):
            return mem_kc.get((svc, acc))

        def write(self, svc, acc, val):
            mem_kc[(svc, acc)] = val

        def delete(self, svc, acc):
            return mem_kc.pop((svc, acc), None) is not None

    state_dir = tmp_path / "state"
    store = secret_store.SecretStore(state_dir, keychain=_FakeKC())
    store.set("install-1", sm, "SEC", "supersecretkey12345")
    assert store.webhook_secret("install-1", sm, "SEC", "ci") == "supersecretkey12345"
    assert store.webhook_secret("install-1", sm, "SEC", "other") is None


@pytest.mark.parametrize(
    "extra_toml",
    [
        'tier = "builtin"\n',
        'tier = "core"\n',
        "default_enabled = true\n",
        'tier = "builtin"\ndefault_enabled = true\n',
        'tier = "catalog"\ndefault_enabled = true\n',
    ],
)
def test_catalog_and_sidecar_reject_tier_escalation_and_default_enabled(tmp_path: Path, extra_toml: str) -> None:
    _write_entry(tmp_path)
    (tmp_path / "carnivore.toml").write_text(
        f"""
schema = 2
id = "evilplug"
name = "Evil"
version = "1.0.0"
kind = "plugin"
description = "Tries to escalate tier or default_enabled"
author = "Attacker"
{extra_toml}
[run]
cmd = ["python3", "main.py"]
""",
        encoding="utf-8",
    )
    with pytest.raises(ManifestV2Error):
        load_manifest_v2(tmp_path)
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(tmp_path, "evilplug")
    with pytest.raises(CplugGateRefusal) as exc_info:
        install_gates.evaluate("attacker/evilplug", tmp_path)
    assert exc_info.value.code == install_gates.MANIFEST_INVALID


def test_non_list_requires_and_requires_core_raise_manifest_v2_error(tmp_path: Path) -> None:
    base = {
        "schema": 2,
        "id": "badreq",
        "name": "Bad Req",
        "version": "1.0.0",
        "kind": "theme",
        "description": "Malformed requires",
        "author": "Tester",
    }
    for bad in (
        {"requires": None},
        {"requires": 123},
        {"requires_core": None},
        {"requires_core": 123},
        {"requires_core": [{}]},
    ):
        with pytest.raises(ManifestV2Error):
            parse_manifest_v2({**base, **bad})

    (tmp_path / "carnivore.json").write_text(json.dumps({**base, "requires": None}), encoding="utf-8")
    with pytest.raises(SidecarManifestError):
        load_sidecar_manifest(tmp_path, "badreq")
    with pytest.raises(CplugGateRefusal) as exc_info:
        install_gates.evaluate("acme/badreq", tmp_path)
    assert exc_info.value.code == install_gates.MANIFEST_INVALID

    for dup_payload, pattern in (
        ({"requires": ["huddle", "huddle"]}, "twice"),
        ({"requires": [""]}, "list of other plugin ids"),
        ({"requires_core": "crosstalk"}, "list of names"),
        ({"requires_core": ["crosstalk", "crosstalk"]}, "twice"),
        ({"requires_core": ["nonexistent_core"]}, "unknown core feature"),
    ):
        with pytest.raises(ManifestV2Error, match=pattern):
            parse_manifest_v2({**base, **dup_payload})


def test_omitted_tool_input_schema_normalizes_to_object(tmp_path: Path) -> None:
    _write_entry(tmp_path)
    (tmp_path / "carnivore.toml").write_text(
        """
schema = 2
id = "noschema"
name = "No Schema"
version = "1.0.0"
kind = "plugin"
description = "Tool without inputSchema"
author = "Tester"

[run]
cmd = ["python3", "main.py"]

[mcp]
[[mcp.tools]]
name = "read_info"
description = "Read info"
gate = "read"
""",
        encoding="utf-8",
    )
    m = load_manifest_v2(tmp_path)
    assert m.tools == ({"name": "read_info", "description": "Read info", "gate": "read", "inputSchema": {"type": "object"}},)


@pytest.mark.parametrize(
    "patch",
    [
        {"ui": {"routes": [{}]}},
        {"ui": {"topics": [{}]}},
        {"ui": {"views": [{"name": "v", "surfaces": [{}], "files": ["index.html"]}]}},
        {"ui": {"views": [{"name": "v", "surfaces": ["panel"], "files": [{}]}]}},
        {"permissions": {"network": [{"host": "api.example.com", "auth": {"secret": {}, "header": "X-Key", "scheme": "Bearer"}}]}},
    ],
)
def test_unhashable_dict_inputs_raise_manifest_v2_error_and_gate_refusal(tmp_path: Path, patch: dict) -> None:
    raw = {
        "schema": 2,
        "id": "badui",
        "name": "Bad UI",
        "version": "1.0.0",
        "kind": "theme",
        "description": "Rejects unhashable dict elements cleanly",
        "author": "Tester",
        **patch,
    }
    with pytest.raises(ManifestV2Error):
        parse_manifest_v2(raw)

    (tmp_path / "carnivore.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(CplugGateRefusal) as exc_info:
        install_gates.evaluate("acme/badui", tmp_path)
    assert exc_info.value.code == install_gates.MANIFEST_INVALID


@pytest.mark.parametrize(
    "toml_snippet",
    [
        "[mcp]\n[[mcp.tools]]\nname = 't'\ndescription = 'd'\ngate = 'read'\n[mcp.tools.inputSchema]\ntype = 'object'\ncreated = 2026-01-01\n",
        "[mcp]\n[[mcp.tools]]\nname = 't'\ndescription = 'd'\ngate = 'read'\n[mcp.tools.inputSchema]\ntype = 'object'\ncreated = 2026-01-01T12:00:00Z\n",
        "[mcp]\n[[mcp.tools]]\nname = 't'\ndescription = 'd'\ngate = 'read'\n[mcp.tools.inputSchema]\ntype = 'object'\ntimeout = 12:00:00\n",
        "[mcp]\n[[mcp.tools]]\nname = 't'\ndescription = 'd'\ngate = 'read'\n[mcp.tools.inputSchema]\ntype = 'object'\nweight = nan\n",
        "[mcp]\n[[mcp.tools]]\nname = 't'\ndescription = 'd'\ngate = 'read'\n[mcp.tools.inputSchema]\ntype = 'object'\nweight = inf\n",
        "[settings_schema]\nstarted = 2026-01-01\n",
        "[ui.contribute.panel]\ncreated = 2026-01-01\n",
    ],
)
def test_toml_non_json_scalars_raise_manifest_v2_error(tmp_path: Path, toml_snippet: str) -> None:
    _write_entry(tmp_path)
    (tmp_path / "carnivore.toml").write_text(
        f"""
schema = 2
id = "badtoml"
name = "Bad TOML"
version = "1.0.0"
kind = "plugin"
description = "Rejects TOML date/time/nan/inf cleanly"
author = "Tester"

[run]
cmd = ["python3", "main.py"]

{toml_snippet}
""",
        encoding="utf-8",
    )
    with pytest.raises(ManifestV2Error):
        load_manifest_v2(tmp_path)


@pytest.mark.parametrize("bad_ver", [False, 0, [], {}, None, ""])
def test_falsy_or_non_string_min_app_version_raises_manifest_v2_error(bad_ver) -> None:
    raw = {
        "schema": 2,
        "id": "badver",
        "name": "Bad Version",
        "version": "1.0.0",
        "kind": "theme",
        "description": "Rejects falsy/non-string min_app_version",
        "author": "Tester",
        "min_app_version": bad_ver,
    }
    with pytest.raises(ManifestV2Error, match="min_app_version"):
        parse_manifest_v2(raw)


def test_sideload_kind_and_routes_v2_toml_and_json(tmp_path: Path) -> None:
    from src.core.skills import kinds
    from src.plugins.host import sideload, sideload_kind, sideload_routes

    toml_dir = tmp_path / "toml_plug"
    toml_dir.mkdir()
    (toml_dir / "carnivore.toml").write_text(
        'schema = 2\nid = "tomlplug"\nname = "TOML Plug"\nversion = "0.1.0"\nkind = "theme"\ndescription = "d"\nauthor = "Tester"\n',
        encoding="utf-8",
    )
    assert sideload_kind.detect(toml_dir) == kinds.KIND_CPLUG
    assert sideload_routes.name_of(toml_dir, None) == "tomlplug"

    json_dir = tmp_path / "json_plug"
    json_dir.mkdir()
    (json_dir / "carnivore.json").write_text(
        json.dumps({"schema": 2, "id": "jsonplug", "name": "JSON Plug", "version": "0.1.0", "kind": "theme", "description": "d", "author": "Tester"}),
        encoding="utf-8",
    )
    assert sideload_kind.detect(json_dir) == kinds.KIND_CPLUG
    assert sideload_routes.name_of(json_dir, None) == "jsonplug"

    both_dir = tmp_path / "both_dir"
    both_dir.mkdir()
    (both_dir / "carnivore.toml").write_text('schema = 2\nid = "a"\n', encoding="utf-8")
    (both_dir / "theme.json").write_text('{"name": "t"}', encoding="utf-8")
    with pytest.raises(sideload.SideloadRefused) as exc_info:
        sideload_kind.detect(both_dir)
    assert exc_info.value.code == "kind_ambiguous"

    bare_widget = tmp_path / "bare_widget"
    bare_widget.mkdir()
    (bare_widget / "carnivore.json").write_text('{"kind": "widget", "name": "w"}', encoding="utf-8")
    with pytest.raises(sideload.SideloadRefused) as exc_info2:
        sideload_kind.detect(bare_widget)
    assert exc_info2.value.code == "kind_unsupported"


def test_check_and_load_v2_tier0_and_polyglot(tmp_path: Path) -> None:
    from scripts.plugin.check import check_folder

    tier0_dir = tmp_path / "tier0_pack"
    tier0_dir.mkdir()
    (tier0_dir / "carnivore.toml").write_text(
        'schema = 2\nid = "hellotier0"\nname = "Hello Tier0"\nversion = "1.0.0"\nkind = "widget"\ndescription = "No-code widget"\nauthor = "Tester"\n[ui.widget]\ntitle = "Hi"\ndocument = { schema = 1, root = { type = "text", value = "Static" } }\n',
        encoding="utf-8",
    )
    report = check_folder(tier0_dir)
    assert report.ok and report.manifest_v2 is not None and report.manifest_v2.tier0 is True, report.errors
    sm_t0 = load_sidecar_manifest(tier0_dir, "hellotier0", allow_local=True)
    assert sm_t0.id == "hellotier0" and sm_t0.tier0 is True

    poly_dir = tmp_path / "poly_pack"
    poly_dir.mkdir()
    (poly_dir / "main.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")
    (poly_dir / "carnivore.toml").write_text(
        'schema = 2\nid = "hellobash"\nname = "Hello Bash"\nversion = "1.0.0"\nkind = "plugin"\ndescription = "Bash plugin"\nauthor = "Tester"\n[run]\ncmd = ["bash", "main.sh"]\nmode = "oneshot"\n',
        encoding="utf-8",
    )
    poly_report = check_folder(poly_dir)
    assert poly_report.ok and poly_report.manifest_v2 is not None, poly_report.errors
    sm_poly = load_sidecar_manifest(poly_dir, "hellobash", allow_local=True)
    assert sm_poly.run_mode == "oneshot" and sm_poly.run_cmd == ("bash", "main.sh")


def test_manifest_v2_rejects_bad_channel_port_duplicate_commands_and_coexisting_cplug_json(tmp_path: Path) -> None:
    from scripts.plugin.check import check_folder

    base = {
        "schema": 2,
        "id": "badchan",
        "name": "Bad Chan",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "d",
        "author": "Tester",
        "permissions": {"network": ["api.example.com"]},
    }
    for bad_url in (
        "https://api.example.com:abc/hook",
        "https://api.example.com:99999/hook",
        "https://api.example.com:0/hook",
    ):
        with pytest.raises(ManifestV2Error):
            parse_manifest_v2({**base, "channels": {"alerts": {"url": bad_url}}})

    with pytest.raises(ManifestV2Error, match="duplicate id"):
        parse_manifest_v2(
            {
                **base,
                "permissions": {},
                "ui": {
                    "commands": [
                        {"id": "dup_cmd", "title": "First"},
                        {"id": "dup_cmd", "title": "Second"},
                    ]
                },
            }
        )

    coexist_dir = tmp_path / "coexist"
    coexist_dir.mkdir()
    (coexist_dir / "carnivore.toml").write_text(
        'schema = 2\nid = "x"\nname = "X"\nversion = "1.0.0"\nkind = "widget"\ndescription = "d"\nauthor = "a"\n',
        encoding="utf-8",
    )
    (coexist_dir / "cplug.json").write_text('{"schema": 1}', encoding="utf-8")
    coexist_report = check_folder(coexist_dir)
    assert not coexist_report.ok and any("cplug.json" in err for err in coexist_report.errors)
    with pytest.raises(SidecarManifestError, match="cplug.json"):
        load_sidecar_manifest(coexist_dir, "x", allow_local=True)


def test_dev_frame_prefixes_and_trust_unrestricted_export() -> None:
    from src.plugins.sdk.manifest_v2 import TRUST_UNRESTRICTED

    assert TRUST_UNRESTRICTED == "unrestricted"
    base = {
        "schema": 2,
        "id": "devplug",
        "name": "Dev Plug",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Dev plugin",
        "author": "Carnivore",
        "tier": "dev",
        "ui": {"dev_frame_prefixes": ["/draft-harness/", "/preview/"]},
    }
    parsed = parse_manifest_v2(base, tier="dev", allow_tier_override=True)
    assert parsed.ui_meta["dev_frame_prefixes"] == ["/draft-harness/", "/preview/"]

    for tier in ("builtin", "core", "catalog", "local"):
        with pytest.raises(ManifestV2Error, match="dev"):
            parse_manifest_v2({**base, "tier": tier}, tier=tier, allow_tier_override=True)

    for bad_prefixes in (
        "draft-harness",
        ["draft-harness/"],
        ["/draft-harness"],
        [""],
        ["/"],
        ["//"],
        ["/./"],
        ["/draft/./harness/"],
        ["/draft//harness/"],
        ["/../escape/"],
        ["/%2e%2e/"],
        ["/draft/%2E%2E/"],
        ["/draft/%2f/"],
        ["/draft/%5c/"],
        ["/draft\\harness/"],
        ["/draft harness/"],
        ["/draft\x00/"],
        ["/draft/?q=1/"],
        ["/draft/#frag/"],
        ["/dup/", "/dup/"],
        [{}],
        [[]],
        [123],
    ):
        with pytest.raises(ManifestV2Error):
            parse_manifest_v2({**base, "ui": {"dev_frame_prefixes": bad_prefixes}}, tier="dev", allow_tier_override=True)


def test_local_tier_v2_sideload_and_reload_accepted_while_install_gates_reject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from src.core.skills import kinds
    from src.plugins.host import developer_mode, identity, sidecar_registry, sideload

    state_dir = tmp_path / "state"
    src_dir = tmp_path / "src_local"
    src_dir.mkdir()
    _write_entry(src_dir)
    (src_dir / "carnivore.toml").write_text(
        """
schema = 2
id = "localv2"
name = "Local V2"
version = "1.0.0"
kind = "plugin"
description = "Local tier v2 sideload"
author = "Dev"
tier = "local"

[run]
cmd = ["python3", "main.py"]
""",
        encoding="utf-8",
    )

    with pytest.raises(CplugGateRefusal) as exc_gate:
        install_gates.evaluate("acme/localv2", src_dir)
    assert exc_gate.value.code == install_gates.MANIFEST_INVALID

    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    sideload.set_switch(state_dir, True)
    staging, files, manifest = sideload.stage(state_dir, "localv2", src_dir)
    assert manifest.tier == "local"
    rec = identity.register_install(state_dir, "localv2", "local/localv2", set(), sideload=True)
    sideload.install_staged(state_dir, "localv2", staging, files, manifest.code_digest, src_dir)

    rows = [SimpleNamespace(item_id="local/localv2", kind=kinds.KIND_CPLUG, source_index_url="local", publisher_key_id="local")]
    reg = sidecar_registry.SidecarRegistry(state_dir, lambda: rows)
    assert reg.reload() == 1
    loaded = reg.find("localv2")
    assert loaded is not None
    assert loaded.install_key == rec.uuid
    assert loaded.manifest.tier == "local"

