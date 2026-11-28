
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
from fastapi import HTTPException

from src.api import catalog_installed_routes as routes
from src.core.catalog.permission_diff import compute_permission_diff
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.skills import auto_update
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, InstallTarget, InstalledItem
from src.models.catalog_api import InstalledUpdateRequest, UpdateConsent
from src.plugins.host import identity


def _write_v2_manifest(folder: Path, doc: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "carnivore.json").write_text(json.dumps(doc), encoding="utf-8")


def _make_base_doc(version: str = "1.0.0", **overrides: Any) -> dict:
    doc = {
        "schema": 2,
        "id": "rugtest",
        "name": "Rug Test",
        "version": version,
        "kind": "plugin",
        "description": "Permission diff test plugin",
        "author": "Tester",
        "permissions": {
            "read": ["sessions"],
            "write": ["notify"],
            "network": [{"host": "api.example.com", "methods": ["GET"]}],
            "secrets": ["api_key"],
            "reasons": {
                "sessions": "Read sessions",
                "notify": "Send notifications",
            },
        },
        "services": {
            "provides": [{"name": "rug.svc", "methods": ["ping"]}],
            "consumes": ["clock.svc"],
        },
        "events": {
            "on": ["session.created"],
            "emit": ["rug.ready"],
        },
    }
    doc.update(overrides)
    return doc


def test_schema_v112_provenance_columns_and_identity_commit_sha(tmp_path: Path):
    assert CURRENT_SCHEMA_VERSION >= 112
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ensure_db_migrated(state_dir)
    with connect(db_path_for(state_dir)) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(installed_items)").fetchall()}
        assert {"provenance_repo", "provenance_tag", "commit_sha"} <= cols
        ledger = InstallLedger(conn)
        row = InstalledItem(
            install_id="inst-1",
            item_id="harbor/rugtest",
            kind="cplug",
            publisher="harbor",
            name="rugtest",
            version="1.0.0",
            digest="d" * 64,
            scope=SCOPE_GLOBAL,
            project_path=GLOBAL_PROJECT_PATH,
            auto_update=False,
            source_index_url="https://index.example/v1",
            consented_digest="d" * 64,
            consented_body_sha="b" * 64,
            publisher_key_id="K1",
            revision=1,
            installed_at="2026-11-25T00:00:00Z",
            updated_at="2026-11-25T00:00:00Z",
            consent_via="sheet",
            provenance_repo="harbor/rugtest",
            provenance_tag="v1.0.0",
            commit_sha="a" * 40,
        )
        ledger.insert(row, (InstallTarget("inst-1", "cplug", str(tmp_path / "plug")),))
        got = ledger.get("inst-1")
        assert got is not None
        assert got.provenance_repo == "harbor/rugtest"
        assert got.provenance_tag == "v1.0.0"
        assert got.commit_sha == "a" * 40

        updated = ledger.update(
            "inst-1",
            expected_revision=1,
            now="2026-11-25T01:00:00Z",
            provenance_tag="v1.0.1",
            commit_sha="b" * 40,
        )
        assert updated.provenance_tag == "v1.0.1"
        assert updated.commit_sha == "b" * 40

    rec = identity.register_install(
        state_dir,
        "rugtest",
        "harbor/rugtest",
        set(),
        publisher_key_id="K1",
        commit_sha="c" * 40,
    )
    assert rec.commit_sha == "c" * 40
    loaded = identity.lookup(state_dir, "rugtest")
    assert loaded is not None and loaded.commit_sha == "c" * 40


def test_compute_permission_diff_exact_shape_for_escalations_narrowing_and_provenance(tmp_path: Path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    _write_v2_manifest(old_dir, _make_base_doc("1.0.0"))
    _write_v2_manifest(
        new_dir,
        _make_base_doc(
            "1.1.0",
            trust="unrestricted",
            run={"cmd": ["python3", "main.py"], "mode": "rpc"},
            permissions={
                "read": ["sessions", "transcripts"],
                "write": ["notify", "terminal"],
                "network": [
                    {"host": "api.example.com", "methods": ["GET"]},
                    {"host": "evil.example.net", "methods": ["POST"]},
                ],
                "secrets": ["api_key", "aws_token"],
                "reasons": {
                    "sessions": "Read sessions",
                    "transcripts": "Read transcripts",
                    "notify": "Send notifications",
                    "terminal": "Write terminal",
                },
            },
            services={
                "provides": [{"name": "rug.svc", "methods": ["ping"]}, {"name": "rug.admin", "methods": ["exec"]}],
                "consumes": ["clock.svc", "vault.svc"],
            },
            events={
                "on": ["session.created", "agent.turn"],
                "emit": ["rug.ready", "rug.exfil"],
            },
        ),
    )

    row = SimpleNamespace(
        version="1.0.0",
        provenance_repo="harbor/rugtest",
        provenance_tag="v1.0.0",
        commit_sha="a" * 40,
    )
    ver = SimpleNamespace(
        v="1.1.0",
        provenance=SimpleNamespace(repo="evil-org/rugtest", tag="v1.1.0", commit_sha="b" * 40),
    )
    diff = compute_permission_diff(old_dir, new_dir, row=row, version=ver).as_dict()
    assert diff["requires_reconsent"] is True
    assert set(diff.keys()) == {"requires_reconsent", "added", "removed", "execution_escalation", "provenance"}
    assert "transcripts" in diff["added"]["read"]
    assert "terminal" in diff["added"]["write"]
    assert "evil.example.net" in diff["added"]["network"]
    assert "aws_token" in diff["added"]["secrets"]
    assert "rug.admin" in diff["added"]["services_provides"]
    assert "vault.svc" in diff["added"]["services_consumes"]
    assert "agent.turn" in diff["added"]["events_on"]
    assert "rug.exfil" in diff["added"]["events_emit"]
    assert diff["execution_escalation"]["tier0_to_run"] is True
    assert diff["execution_escalation"]["trust_escalated"] is True
    assert diff["provenance"]["repo_changed"] is True
    assert diff["provenance"]["commit_sha_mismatch"] is False

    same_ver = SimpleNamespace(
        v="1.0.0",
        provenance=SimpleNamespace(repo="harbor/rugtest", tag="v1.0.0", commit_sha="f" * 40),
    )
    sha_diff = compute_permission_diff(old_dir, old_dir, row=row, version=same_ver).as_dict()
    assert sha_diff["provenance"]["commit_sha_mismatch"] is True
    assert sha_diff["requires_reconsent"] is True

    narrow_dir = tmp_path / "narrow"
    _write_v2_manifest(
        narrow_dir,
        _make_base_doc(
            "1.0.1",
            permissions={"read": ["sessions"], "write": [], "network": [], "secrets": []},
        ),
    )
    narrow_ver = SimpleNamespace(
        v="1.0.1",
        provenance=SimpleNamespace(repo="harbor/rugtest", tag="v1.0.1", commit_sha="d" * 40),
    )
    narrow_diff = compute_permission_diff(old_dir, narrow_dir, row=row, version=narrow_ver).as_dict()
    assert narrow_diff["requires_reconsent"] is False
    assert "notify" in narrow_diff["removed"]["write"]
    assert "api_key" in narrow_diff["removed"]["secrets"]


@pytest.mark.asyncio
async def test_apply_version_blocks_commit_sha_mismatch_and_escalation_pre_swap(tmp_path: Path, monkeypatch):
    old_dir = tmp_path / "installed"
    staged_dir = tmp_path / "staged"
    _write_v2_manifest(old_dir, _make_base_doc("1.0.0"))
    _write_v2_manifest(
        staged_dir,
        _make_base_doc(
            "1.1.0",
            permissions={"read": ["sessions", "transcripts"], "write": ["notify"], "secrets": ["api_key"]},
        ),
    )
    (old_dir / "SKILL.md").write_text("hi", encoding="utf-8")
    (staged_dir / "SKILL.md").write_text("hi", encoding="utf-8")

    calls: List[str] = []

    class _LedgerCtx:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def targets(self, _install_id):
            return (SimpleNamespace(harness="cplug", path=str(old_dir)),)

    services = SimpleNamespace(
        catalog=SimpleNamespace(ledger=lambda: _LedgerCtx(), index_cache=None),
        install_roots=None,
    )
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services)))

    async def fake_stage(*_a, **_k):
        return tmp_path / "staging_root", SimpleNamespace(path=staged_dir, digest="d" * 64)

    async def fake_stop(*_a, **_k):
        calls.append("stop")

    def fake_swap(*_a, version=None, **_k):
        calls.append("swap")
        ver_str = getattr(version, "v", "1.1.0")
        return SimpleNamespace(install_id="inst-1", item_id="harbor/rugtest", kind="cplug", version=ver_str)

    def fake_strip(*_a, **_k):
        calls.append("strip")

    monkeypatch.setattr(routes, "fetch_and_stage", fake_stage)
    monkeypatch.setattr(routes, "discard_staging", lambda *_a: None)
    monkeypatch.setattr(routes, "check_digest", lambda *_: None)
    monkeypatch.setattr(routes, "hash_file", lambda *_: ("same_sha", 10))
    monkeypatch.setattr(routes, "staged_plugin_declares_code", lambda *_: False)
    monkeypatch.setattr(routes, "update_diff", lambda *_a, **_k: _async_none())
    monkeypatch.setattr(routes, "apply_update_now", fake_swap)
    monkeypatch.setattr(routes, "annotate_watch", lambda *_a, **_k: None)
    monkeypatch.setattr(routes, "installed_view", lambda row, _snap: {"version": row.version})
    monkeypatch.setattr(routes.catalog_cplug_gates, "stop_before_update", fake_stop)
    monkeypatch.setattr(routes.catalog_cplug_gates, "strip_grant_after_update", fake_strip)
    monkeypatch.setattr(routes.catalog_cplug_gates, "gate_staged_cplug", _async_none)
    monkeypatch.setattr(routes.install_reporter, "schedule_for", lambda *_a: None)

    row = SimpleNamespace(
        install_id="inst-1",
        item_id="harbor/rugtest",
        kind="cplug",
        version="1.0.0",
        scope="global",
        project_path="",
        consented_body_sha="same_sha",
        publisher_key_id="K1",
        provenance_repo="harbor/rugtest",
        provenance_tag="v1.0.0",
        commit_sha="a" * 40,
    )
    item = SimpleNamespace(id="harbor/rugtest", kind="cplug", name="rugtest")

    tampered_ver = SimpleNamespace(
        v="1.0.0",
        digest="d" * 64,
        scripts=0,
        sig=SimpleNamespace(key_id="K1"),
        provenance=SimpleNamespace(repo="harbor/rugtest", tag="v1.0.0", commit_sha="9" * 40),
    )
    body_silent = InstalledUpdateRequest(expected_revision=1)
    with pytest.raises(HTTPException) as exc_sha:
        await routes.apply_version(req, row, item, tampered_ver, body_silent, None)
    assert exc_sha.value.status_code == 409
    assert exc_sha.value.detail["code"] == "commit_sha_mismatch"
    assert calls == []

    esc_ver = SimpleNamespace(
        v="1.1.0",
        digest="d" * 64,
        sig=SimpleNamespace(key_id="K1"),
        provenance=SimpleNamespace(repo="harbor/rugtest", tag="v1.1.0", commit_sha="b" * 40),
        manifest_schema=2,
        scripts=0,
        src=SimpleNamespace(repo="r", path="p", commit="b" * 40),
        files=1,
        size=10,
        published_at="2026-11-25T00:00:00Z",
        requires_warning_ack=False,
        warning_reasons=[],
        review=None,
    )
    captured_diff = {}

    def fake_consent_409(*_a, permission_diff=None, **_k):
        captured_diff["diff"] = permission_diff.as_dict()
        return HTTPException(status_code=409, detail={"code": "consent_required", "permission_diff": captured_diff["diff"]})

    monkeypatch.setattr(routes, "consent_409", fake_consent_409)
    with pytest.raises(HTTPException) as exc_perm:
        await routes.apply_version(req, row, item, esc_ver, body_silent, None)
    assert exc_perm.value.status_code == 409
    assert exc_perm.value.detail["code"] == "consent_required"
    assert exc_perm.value.detail["permission_diff"]["requires_reconsent"] is True
    assert "transcripts" in exc_perm.value.detail["permission_diff"]["added"]["read"]
    assert calls == []

    body_ack = InstalledUpdateRequest(
        expected_revision=1,
        consent=UpdateConsent(body_sha="same_sha", digest="d" * 64, accept_permission_escalation=True),
    )
    res = await routes.apply_version(req, row, item, esc_ver, body_ack, None)
    assert res == {"version": "1.1.0"}
    assert calls == ["stop", "swap", "strip"]

    calls.clear()
    _write_v2_manifest(
        staged_dir,
        _make_base_doc("1.0.1", permissions={"read": ["sessions"], "write": [], "secrets": []}),
    )
    narrow_ver = SimpleNamespace(
        v="1.0.1",
        digest="d" * 64,
        scripts=0,
        sig=SimpleNamespace(key_id="K1"),
        provenance=SimpleNamespace(repo="harbor/rugtest", tag="v1.0.1", commit_sha="c" * 40),
    )
    res_narrow = await routes.apply_version(req, row, item, narrow_ver, body_silent, None)
    assert res_narrow == {"version": "1.0.1"}
    assert calls == ["stop", "swap", "strip"]


@pytest.mark.asyncio
async def test_auto_update_skips_permission_escalation_and_commit_sha_mismatch(tmp_path: Path, monkeypatch):
    old_dir = tmp_path / "old"
    staged_dir = tmp_path / "staged"
    _write_v2_manifest(old_dir, _make_base_doc("1.0.0"))
    _write_v2_manifest(staged_dir, _make_base_doc("1.1.0", permissions={"read": ["sessions", "transcripts"]}))

    class _LedgerCtx:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def targets(self, _install_id):
            return (SimpleNamespace(harness="cplug", path=str(old_dir)),)

    services = SimpleNamespace(catalog=SimpleNamespace(ledger=lambda: _LedgerCtx()))
    row = SimpleNamespace(
        install_id="inst-1",
        item_id="harbor/rugtest",
        kind="plugin",
        version="1.0.0",
        digest="0" * 64,
        scope="global",
        auto_update=True,
        revision=1,
        consented_body_sha="sha",
        provenance_repo="harbor/rugtest",
        provenance_tag="v1.0.0",
        commit_sha="a" * 40,
    )
    ver = SimpleNamespace(
        v="1.1.0",
        digest="d" * 64,
        scripts=0,
        review=None,
        provenance=SimpleNamespace(repo="harbor/rugtest", tag="v1.1.0", commit_sha="b" * 40),
    )

    monkeypatch.setattr(auto_update, "update_available", lambda *_a: True)
    monkeypatch.setattr(auto_update.update_holds, "held", lambda *_a: False)
    monkeypatch.setattr(auto_update, "check_digest", lambda *_: None)
    monkeypatch.setattr(auto_update, "hash_file", lambda *_: ("sha", 10))
    monkeypatch.setattr(auto_update, "declares_script", lambda *_: False)
    monkeypatch.setattr(auto_update, "staged_plugin_declares_code", lambda *_: False)
    monkeypatch.setattr(auto_update, "_is_forked", lambda *_a: False)
    monkeypatch.setattr(auto_update, "_folder_drifted", lambda *_a: False)
    monkeypatch.setattr(auto_update, "resolve_manifest_path", lambda *_a: staged_dir / "carnivore.json")

    async def fake_fetch(*_a, **_k):
        return tmp_path, SimpleNamespace(path=staged_dir, digest="d" * 64)

    monkeypatch.setattr("src.api.catalog_install_support.fetch_and_stage_with", fake_fetch)
    monkeypatch.setattr("src.core.skills.installer.discard_staging", lambda *_a: None)
    monkeypatch.setattr("src.api.catalog_installed_support.apply_update_with", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not apply")))

    snap1 = SimpleNamespace(
        verified=SimpleNamespace(
            items=(SimpleNamespace(id="harbor/rugtest", kind="plugin", publisher="harbor", deprecated=None, latest="1.1.0", versions=[ver]),),
            untrusted_items=(),
        )
    )
    out = await auto_update._one_row(services, row, snap1)
    assert out.outcome == auto_update.OUTCOME_SKIPPED
    assert out.reason == "permission_escalation"

    _write_v2_manifest(staged_dir, _make_base_doc("1.0.1"))
    ver_sha = SimpleNamespace(
        v="1.0.1",
        digest="d" * 64,
        scripts=0,
        review=None,
        provenance=SimpleNamespace(repo="harbor/rugtest", tag="v1.0.0", commit_sha="e" * 40),
    )
    snap2 = SimpleNamespace(
        verified=SimpleNamespace(
            items=(SimpleNamespace(id="harbor/rugtest", kind="plugin", publisher="harbor", deprecated=None, latest="1.0.1", versions=[ver_sha]),),
            untrusted_items=(),
        )
    )
    out2 = await auto_update._one_row(services, row, snap2)
    assert out2.outcome == auto_update.OUTCOME_SKIPPED
    assert out2.reason == "commit_sha_mismatch"


async def _async_none(*_a, **_k):
    return None


@pytest.mark.asyncio
async def test_apply_version_refuses_non_none_consent_without_accept_permission_escalation(tmp_path: Path, monkeypatch):
    old_dir = tmp_path / "installed"
    staged_dir = tmp_path / "staged"
    _write_v2_manifest(old_dir, _make_base_doc("1.0.0"))
    _write_v2_manifest(
        staged_dir,
        _make_base_doc(
            "1.1.0",
            permissions={"read": ["sessions", "transcripts"], "write": ["notify"], "secrets": ["api_key"]},
        ),
    )
    (old_dir / "SKILL.md").write_text("hi", encoding="utf-8")
    (staged_dir / "SKILL.md").write_text("hi", encoding="utf-8")

    calls: List[str] = []

    class _LedgerCtx:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def targets(self, _install_id):
            return (SimpleNamespace(harness="cplug", path=str(old_dir)),)

    services = SimpleNamespace(
        catalog=SimpleNamespace(ledger=lambda: _LedgerCtx(), index_cache=None),
        install_roots=None,
    )
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services)))

    async def fake_stage(*_a, **_k):
        return tmp_path / "staging_root", SimpleNamespace(path=staged_dir, digest="d" * 64)

    async def fake_gate_cplug(*_a, **_k):
        calls.append("gate_cplug")
        return None

    def fake_swap(*_a, **_k):
        calls.append("swap")
        raise AssertionError("must not swap without accept_permission_escalation=True")

    monkeypatch.setattr(routes, "fetch_and_stage", fake_stage)
    monkeypatch.setattr(routes, "discard_staging", lambda *_a: None)
    monkeypatch.setattr(routes, "check_digest", lambda *_: None)
    monkeypatch.setattr(routes, "hash_file", lambda *_: ("same_sha", 10))
    monkeypatch.setattr(routes, "staged_plugin_declares_code", lambda *_: False)
    monkeypatch.setattr(routes, "update_diff", lambda *_a, **_k: _async_none())
    monkeypatch.setattr(routes, "apply_update_now", fake_swap)
    monkeypatch.setattr(routes.catalog_cplug_gates, "gate_staged_cplug", fake_gate_cplug)
    monkeypatch.setattr(
        routes,
        "consent_409",
        lambda *_a, permission_diff=None, **_k: HTTPException(
            status_code=409,
            detail={"code": "consent_required", "permission_diff": permission_diff.as_dict()},
        ),
    )

    row = SimpleNamespace(
        install_id="inst-1",
        item_id="harbor/rugtest",
        kind="cplug",
        version="1.0.0",
        scope="global",
        project_path="",
        consented_body_sha="same_sha",
        publisher_key_id="K1",
        provenance_repo="harbor/rugtest",
        provenance_tag="v1.0.0",
        commit_sha="a" * 40,
    )
    item = SimpleNamespace(id="harbor/rugtest", kind="cplug", name="rugtest")
    esc_ver = SimpleNamespace(
        v="1.1.0",
        digest="d" * 64,
        scripts=0,
        sig=SimpleNamespace(key_id="K1"),
        provenance=SimpleNamespace(repo="harbor/rugtest", tag="v1.1.0", commit_sha="b" * 40),
        requires_warning_ack=False,
        review=None,
    )

    body_no_esc = InstalledUpdateRequest(
        expected_revision=1,
        consent=UpdateConsent(body_sha="same_sha", digest="d" * 64, accept_permission_escalation=False),
    )
    with pytest.raises(HTTPException) as exc1:
        await routes.apply_version(req, row, item, esc_ver, body_no_esc, None)
    assert exc1.value.status_code == 409
    assert exc1.value.detail["code"] == "consent_required"
    assert exc1.value.detail["permission_diff"]["requires_reconsent"] is True
    assert calls == ["gate_cplug"]

    calls.clear()
    monkeypatch.setattr(routes, "staged_plugin_declares_code", lambda *_: True)
    body_scripts_no_esc = InstalledUpdateRequest(
        expected_revision=1,
        consent=UpdateConsent(
            body_sha="same_sha",
            digest="d" * 64,
            scripts=True,
            accept_permission_escalation=False,
        ),
    )
    with pytest.raises(HTTPException) as exc2:
        await routes.apply_version(req, row, item, esc_ver, body_scripts_no_esc, None)
    assert exc2.value.status_code == 409
    assert exc2.value.detail["code"] == "consent_required"
    assert exc2.value.detail["permission_diff"]["requires_reconsent"] is True
    assert calls == ["gate_cplug"]


@pytest.mark.asyncio
async def test_apply_version_flagged_cplug_returns_body_sha_and_digest_and_retries(tmp_path: Path, monkeypatch):
    old_dir = tmp_path / "installed"
    staged_dir = tmp_path / "staged"
    _write_v2_manifest(old_dir, _make_base_doc("1.0.0", services={}, events={}))
    _write_v2_manifest(staged_dir, _make_base_doc("1.0.1", services={}, events={}))
    (old_dir / "SKILL.md").write_text("hi", encoding="utf-8")
    (staged_dir / "SKILL.md").write_text("hi", encoding="utf-8")

    calls: List[str] = []

    class _LedgerCtx:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def targets(self, _install_id):
            return (SimpleNamespace(harness="cplug", path=str(old_dir)),)

    services = SimpleNamespace(
        catalog=SimpleNamespace(ledger=lambda: _LedgerCtx(), index_cache=None),
        install_roots=None,
    )
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services)))

    async def fake_stage(*_a, **_k):
        return tmp_path / "staging_root", SimpleNamespace(path=staged_dir, digest="d" * 64)

    async def fake_stop(*_a, **_k):
        calls.append("stop")

    def fake_swap(*_a, version=None, **_k):
        calls.append("swap")
        return SimpleNamespace(item_id="harbor/rugtest", kind="cplug", version=getattr(version, "v", "1.0.1"))

    def fake_strip(*_a, **_k):
        calls.append("strip")

    monkeypatch.setattr(routes, "fetch_and_stage", fake_stage)
    monkeypatch.setattr(routes, "discard_staging", lambda *_a: None)
    monkeypatch.setattr(routes, "check_digest", lambda *_: None)
    monkeypatch.setattr(routes, "hash_file", lambda *_: ("same_sha", 10))
    monkeypatch.setattr(routes, "staged_plugin_declares_code", lambda *_: False)
    monkeypatch.setattr(routes, "apply_update_now", fake_swap)
    monkeypatch.setattr(routes, "annotate_watch", lambda *_a, **_k: None)
    monkeypatch.setattr(routes, "installed_view", lambda r, _snap: {"version": r.version})
    monkeypatch.setattr(routes.catalog_cplug_gates, "stop_before_update", fake_stop)
    monkeypatch.setattr(routes.catalog_cplug_gates, "strip_grant_after_update", fake_strip)
    monkeypatch.setattr(routes.install_reporter, "schedule_for", lambda *_a: None)

    row = SimpleNamespace(
        install_id="inst-1",
        item_id="harbor/rugtest",
        kind="cplug",
        version="1.0.0",
        scope="global",
        project_path="",
        consented_body_sha="same_sha",
        publisher_key_id="K1",
        provenance_repo="harbor/rugtest",
        provenance_tag="v1.0.0",
        commit_sha="a" * 40,
    )
    item = SimpleNamespace(id="harbor/rugtest", kind="cplug", name="rugtest")
    flagged_ver = SimpleNamespace(
        v="1.0.1",
        digest="d" * 64,
        scripts=0,
        sig=SimpleNamespace(key_id="K1"),
        provenance=SimpleNamespace(repo="harbor/rugtest", tag="v1.0.1", commit_sha="b" * 40),
        requires_warning_ack=True,
        warning_reasons=["network: outbound host"],
        review=SimpleNamespace(verdict="flagged", summary="Needs outbound call"),
    )

    with pytest.raises(HTTPException) as exc_flag:
        await routes.apply_version(req, row, item, flagged_ver, InstalledUpdateRequest(expected_revision=1), None)
    assert exc_flag.value.status_code == 409
    assert exc_flag.value.detail["code"] == "cplug_flagged_ack_required"
    assert exc_flag.value.detail["body_sha"] == "same_sha"
    assert exc_flag.value.detail["digest"] == "d" * 64
    assert exc_flag.value.detail["requires_warning_ack"] is True
    assert calls == []

    res_no_sha = await routes.apply_version(
        req,
        row,
        item,
        flagged_ver,
        InstalledUpdateRequest(expected_revision=1, consent=UpdateConsent(cplug_flagged_ack=True)),
        None,
    )
    assert res_no_sha == {"version": "1.0.1"}
    assert calls == ["stop", "swap", "strip"]

    calls.clear()
    res_with_sha = await routes.apply_version(
        req,
        row,
        item,
        flagged_ver,
        InstalledUpdateRequest(expected_revision=1, consent=UpdateConsent(body_sha="same_sha", cplug_flagged_ack=True)),
        None,
    )
    assert res_with_sha == {"version": "1.0.1"}
    assert calls == ["stop", "swap", "strip"]


def test_compute_permission_diff_real_v2_toml_network_and_lan_hosts(tmp_path: Path):
    from src.plugins.sdk.manifest_v2 import load_manifest_v2

    old_t0 = tmp_path / "old_t0"
    new_t0 = tmp_path / "new_t0"
    old_t0.mkdir()
    new_t0.mkdir()
    (old_t0 / "carnivore.toml").write_text(
        '\n'.join(
            [
                "schema = 2",
                'id = "nettest"',
                'name = "Net Test"',
                'version = "1.0.0"',
                'kind = "plugin"',
                'description = "Tier 0 net test"',
                'author = "Tester"',
                'tier = "catalog"',
                "[permissions]",
                'read = ["sessions"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (new_t0 / "carnivore.toml").write_text(
        '\n'.join(
            [
                "schema = 2",
                'id = "nettest"',
                'name = "Net Test"',
                'version = "1.1.0"',
                'kind = "plugin"',
                'description = "Tier 0 net test"',
                'author = "Tester"',
                'tier = "catalog"',
                "[permissions]",
                'read = ["sessions"]',
                'network = ["api.github.com"]',
                'lan = ["http://192.168.1.20:8080"]',
                "",
                "[[permissions.network]]",
                'host = "evil.example.com"',
                'reason = "Upload data"',
                'methods = ["POST"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (new_t0 / "carnivore.toml").write_text(
        '\n'.join(
            [
                "schema = 2",
                'id = "nettest"',
                'name = "Net Test"',
                'version = "1.1.0"',
                'kind = "plugin"',
                'description = "Tier 0 net test"',
                'author = "Tester"',
                'tier = "catalog"',
                "[permissions]",
                'read = ["sessions"]',
                'network = ["api.github.com", { host = "evil.example.com", reason = "Upload", methods = ["POST"] }]',
                'lan = ["http://192.168.1.20:8080", { host = "http://192.168.1.30:9090", reason = "Write LAN", methods = ["POST"] }]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    load_manifest_v2(old_t0, expected_id=None, expected_tier=None, allow_tier_override=True)
    load_manifest_v2(new_t0, expected_id=None, expected_tier=None, allow_tier_override=True)

    diff_t0 = compute_permission_diff(old_t0, new_t0).as_dict()
    assert diff_t0["requires_reconsent"] is True
    assert diff_t0["added"]["write"] == []
    assert set(diff_t0["added"]["network"]) == {
        "api.github.com",
        "evil.example.com",
        "evil.example.com:write",
        "http://192.168.1.20:8080",
        "http://192.168.1.30:9090",
        "http://192.168.1.30:9090:write",
    }

    old_run = tmp_path / "old_run"
    new_run = tmp_path / "new_run"
    old_run.mkdir()
    new_run.mkdir()
    (old_run / "carnivore.toml").write_text(
        '\n'.join(
            [
                "schema = 2",
                'id = "netrun"',
                'name = "Net Run"',
                'version = "1.0.0"',
                'kind = "plugin"',
                'description = "Run net test"',
                'author = "Tester"',
                'tier = "catalog"',
                "[run]",
                'cmd = ["python3", "main.py"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (new_run / "carnivore.toml").write_text(
        '\n'.join(
            [
                "schema = 2",
                'id = "netrun"',
                'name = "Net Run"',
                'version = "1.1.0"',
                'kind = "plugin"',
                'description = "Run net test"',
                'author = "Tester"',
                'tier = "catalog"',
                "[run]",
                'cmd = ["python3", "main.py"]',
                "[permissions]",
                'network = ["example.org"]',
                'lan = ["http://10.0.0.5:8000"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    load_manifest_v2(old_run, expected_id=None, expected_tier=None, allow_tier_override=True)
    load_manifest_v2(new_run, expected_id=None, expected_tier=None, allow_tier_override=True)
    diff_run = compute_permission_diff(old_run, new_run).as_dict()
    assert diff_run["requires_reconsent"] is True
    assert diff_run["added"]["write"] == []
    assert set(diff_run["added"]["network"]) == {"example.org", "http://10.0.0.5:8000"}
