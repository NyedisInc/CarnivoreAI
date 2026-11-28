
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api import catalog_cplug_gates, catalog_install_support
from src.core.skills.kinds import KIND_CPLUG
from src.models.catalog import ItemVersion, UpstreamProvenance


def test_refuse_cplug_scripts_allows_v2_polyglot_but_blocks_v1():
    v1_ver = SimpleNamespace(scripts=1, manifest_schema=None)
    item = SimpleNamespace(id="harbor/poly", kind=KIND_CPLUG)
    assert catalog_install_support.refuse_cplug_scripts(item, v1_ver) is None

    v2_ver = SimpleNamespace(scripts=2, manifest_schema=2)
    assert catalog_install_support.refuse_cplug_scripts(item, v2_ver) is None


def test_upstream_provenance_enforces_40_hex_commit_sha():
    ok = UpstreamProvenance(
        source_type="github",
        repo="harbor/plug",
        tag="v1.0.0",
        commit_sha="a" * 40,
        signature_verified=True,
        key_id="K1",
    )
    assert ok.commit_sha == "a" * 40
    with pytest.raises(ValidationError):
        UpstreamProvenance(source_type="github", repo="harbor/plug", tag="v1.0.0", commit_sha="not-a-sha")

    ver_payload = {
        "v": "1.0.0",
        "src": {"repo": "NyedisInc/CarnivoreAI-Catalog", "path": "plugins/harbor/plug", "commit": "b" * 40},
        "digest": "c" * 64,
        "size": 100,
        "files": 3,
        "scripts": 1,
        "published_at": "2026-11-25T00:00:00Z",
        "sig": {"key_id": "K1", "sig": "sig", "tc": "", "gsig": "gsig"},
        "manifest_schema": 2,
        "provenance": {"source_type": "github", "repo": "harbor/plug", "tag": "v1.0.0", "commit_sha": "a" * 40, "signature_verified": True},
        "requires_warning_ack": True,
        "warning_reasons": ["network: External API access."],
    }
    parsed = ItemVersion.model_validate(ver_payload)
    assert parsed.manifest_schema == 2 and parsed.requires_warning_ack is True
    assert parsed.provenance is not None and parsed.provenance.commit_sha == "a" * 40


def test_check_cplug_consent_requires_flagged_ack_when_flagged():
    facts = SimpleNamespace(sha="f" * 64, facts={})
    flagged_ver = SimpleNamespace(requires_warning_ack=True, review=None)

    no_ack = SimpleNamespace(cplug_accepted=True, cplug_facts_sha="f" * 64, cplug_flagged_ack=False, mod_flagged_ack=False)
    with pytest.raises(HTTPException) as exc:
        catalog_cplug_gates.check_cplug_consent(no_ack, facts, version=flagged_ver)
    assert exc.value.status_code == 409 and exc.value.detail["code"] == "cplug_flagged_ack_required"

    with_ack = SimpleNamespace(cplug_accepted=True, cplug_facts_sha="f" * 64, cplug_flagged_ack=True, mod_flagged_ack=False)
    catalog_cplug_gates.check_cplug_consent(with_ack, facts, version=flagged_ver)


def test_preview_body_populates_warning_reasons_from_review_when_version_field_absent(tmp_path):
    from src.api import catalog_consent
    from src.models.catalog import CatalogItem

    staged_dir = tmp_path / "staged"
    staged_dir.mkdir()
    (staged_dir / "carnivore.toml").write_text(
        'schema = 2\nid = "plug"\nname = "Plug"\nversion = "1.0.0"\nkind = "plugin"\ndescription = "d"\nauthor = "harbor"\n',
        encoding="utf-8",
    )
    ver_payload = {
        "v": "1.0.0",
        "src": {"repo": "NyedisInc/CarnivoreAI-Catalog", "path": "plugins/harbor/plug", "commit": "b" * 40},
        "digest": "c" * 64,
        "size": 100,
        "files": 1,
        "scripts": 0,
        "published_at": "2026-11-25T00:00:00Z",
        "sig": {"key_id": "K1", "sig": "sig", "tc": "", "gsig": "gsig"},
        "review": {
            "status": "reviewed",
            "verdict": "flagged",
            "summary": "Runs a local tool. Contacts external API endpoint.",
            "warnings": [{"kind": "network", "detail": "Calls external API host.", "file": "main.py"}],
            "model": "test/model",
            "reviewed_at": "2026-11-25T00:00:00Z",
        },
    }
    version = ItemVersion.model_validate(ver_payload)
    item = CatalogItem(
        id="harbor/plug",
        kind=KIND_CPLUG,
        name="plug",
        publisher="harbor",
        latest="1.0.0",
        card={"title": "Plug", "brief": "d"},
        fm={"description": "d"},
        versions=[version],
    )
    staged = SimpleNamespace(
        path=staged_dir,
        digest="c" * 64,
        archive=SimpleNamespace(script_members=[]),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                services=SimpleNamespace(
                    catalog=SimpleNamespace(publisher_key_id="K1", index_url=lambda: "https://catalog.example/v1/index.json"),
                    settings_reader=None,
                ),
                sidecar_runtime=None,
            )
        )
    )
    resp = catalog_consent.preview_body(request, item=item, version=version, staged=staged, plan_token=None)
    assert resp.flagged is True
    assert resp.requires_warning_ack is True
    assert resp.warning_reasons == ["network: Calls external API host."]
