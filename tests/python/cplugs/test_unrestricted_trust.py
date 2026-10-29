
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cplugs.host import sidecar_spec
from src.cplugs.host.sidecar_manifest import SidecarManifestError, parse_sidecar_manifest
from src.cplugs.host.sidecar_registry import SidecarDefinition
from src.cplugs.runtime import sandbox
from src.cplugs.runtime.supervisor import Supervisor

PINNED = "3463B8E83B44738B"


def _definition(tmp_path: Path, tier: str, key_id: str, trust: bool = True) -> SidecarDefinition:
    raw = {"schema": 1, "id": "tv", "name": "Tv", "description": "d", "version": "1.0.0", "entry": "main.py", "tools": []}
    if trust:
        raw["trust"] = "unrestricted"
    manifest = replace(parse_sidecar_manifest(raw, "tv", "abc"), tier=tier)
    return SidecarDefinition(manifest, "carnivore/tv", "uuid", tmp_path / "code", tmp_path / "data", key_id)


def _layout(tmp_path: Path) -> sandbox.Layout:
    interp = tmp_path / "a" / "b" / "c" / "d" / "Python"
    return sandbox.Layout(interp, interp.parents[4], tmp_path / "rt", tmp_path / "code", tmp_path / "data")


def _argv(spec, layout: sandbox.Layout):
    if spec.unrestricted:
        return sandbox.build_unrestricted_command(layout, spec.entry, 1)
    return sandbox.build_command(layout, layout.data_dir / "profile.sb", spec.entry, 1)


def test_an_approved_catalog_plugin_launches_without_sandbox_exec(tmp_path):
    spec = sidecar_spec.build_spec(_definition(tmp_path, "catalog", PINNED.lower()), frozenset(), {}, False, PINNED)
    argv = _argv(spec, _layout(tmp_path))
    assert spec.unrestricted and not spec.trust_refusal
    assert "/usr/bin/sandbox-exec" not in argv and "-f" not in argv and argv[0].endswith("Python")
    assert argv[-4:] == [str(tmp_path / "code"), "main", "64", "1"]


def test_an_unrestricted_claim_under_another_key_is_refused(tmp_path):
    spec = sidecar_spec.build_spec(_definition(tmp_path, "catalog", "DEADBEEFDEADBEEF"), frozenset(), {}, True, PINNED)
    assert not spec.unrestricted and spec.trust_refusal == "untrusted_publisher"
    sup = Supervisor(tmp_path, "1.0.0", SimpleNamespace(), lambda *a: None, lambda *a: None, lambda *a: None)
    assert sup.admit(spec) == "trust_refused"
    unpinned = sidecar_spec.build_spec(_definition(tmp_path, "catalog", ""), frozenset(), {}, True, "")
    assert unpinned.trust_refusal == "untrusted_publisher"


def test_no_field_leaves_the_sandboxed_argv_unchanged(tmp_path):
    spec = sidecar_spec.build_spec(_definition(tmp_path, "catalog", "DEADBEEFDEADBEEF", trust=False), frozenset(), {}, True, PINNED)
    argv = _argv(spec, _layout(tmp_path))
    assert not spec.unrestricted and not spec.trust_refusal
    assert argv[:3] == ["/usr/bin/sandbox-exec", "-f", str(tmp_path / "data" / "profile.sb")]
    assert sandbox.allow_env(_layout(tmp_path))["PATH"] == sandbox.SAFE_PATH


def test_a_local_unrestricted_plugin_without_consent_is_not_launched(tmp_path):
    d = _definition(tmp_path, "local", "local")
    sup = Supervisor(tmp_path, "1.0.0", SimpleNamespace(), lambda *a: None, lambda *a: None, lambda *a: None)
    refused = sidecar_spec.build_spec(d, frozenset(), {}, False, PINNED)
    assert refused.trust_refusal == "consent_required" and sup.admit(refused) == "trust_refused"
    consented = sidecar_spec.build_spec(d, frozenset(), {}, True, PINNED)
    assert consented.unrestricted and sup.admit(consented) is None


def test_the_manifest_refuses_any_other_trust_value(tmp_path):
    raw = {"schema": 1, "id": "tv", "name": "Tv", "description": "d", "version": "1.0.0", "entry": "main.py", "trust": "full"}
    with pytest.raises(SidecarManifestError):
        parse_sidecar_manifest(raw, "tv", "abc")
