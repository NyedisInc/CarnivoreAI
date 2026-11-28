
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import List

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from src.api import catalog_cplug_gates, catalog_default_installs, catalog_install_support, catalog_routes, catalog_views
from src.api.auth import require_auth
from src.core import resource_push
from src.core.catalog.index_cache import IndexCache, IndexSnapshot
from src.core.catalog.index_state import RevocationStore
from src.core.catalog.revocation import RevocationRef
from src.core.catalog.verify import verify_index
from src.core.catalog.verify_types import ItemRefusal, VerifiedIndex
from src.models.catalog import CatalogItem, ItemCard, ItemFrontMatter, ItemVersion, ReviewBlock, SignatureBlock, SourceRef, UpstreamProvenance
from src.models.catalog_api import InstallConsent, UpdateConsent
from src.plugins.host import owner_switch, routes as host_routes, runtime as host_runtime, state as owner_state
from src.plugins.host import github_install_support
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.runtime.dispatch import PluginContext
from src.plugins.runtime.supervisor import TIER0_STATE, PluginSpec, Supervisor


def _ver(v: str = "1.0.0", key_id: str = "K1", *, flagged: bool = False) -> ItemVersion:
    return ItemVersion(
        v=v,
        src=SourceRef(repo="NyedisInc/Catalog", path="plugins/acme/demo", commit="a" * 40),
        digest="d" * 64,
        size=100,
        files=2,
        scripts=0,
        published_at="2026-11-25T00:00:00Z",
        sig=SignatureBlock(key_id=key_id, sig="sig", tc="", gsig="gsig"),
        manifest_schema=2,
        requires_warning_ack=flagged,
        warning_reasons=["network: outbound host"] if flagged else [],
        review=ReviewBlock(status="reviewed", verdict="flagged", summary="Needs outbound call") if flagged else None,
    )


def _item(iid: str = "acme/demo", v: str = "1.0.0", key_id: str = "K1", *, flagged: bool = False) -> CatalogItem:
    return CatalogItem(
        id=iid,
        kind="cplug",
        publisher=iid.split("/")[0],
        name=iid.split("/")[-1],
        latest=v,
        card=ItemCard(title="Demo Plugin", brief="Demo", tags=["demo"]),
        fm=ItemFrontMatter(description="Demo plugin description"),
        versions=[_ver(v, key_id, flagged=flagged)],
    )


def test_resolve_item_prefers_409_version_revoked_and_key_untrusted_over_404(tmp_path: Path):
    item = _item("acme/rev", "1.0.0", "KREV")
    store = RevocationStore(tmp_path / "revocations.db")
    verified = VerifiedIndex(
        serial=2,
        generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        items=(),
        untrusted_items=(),
        refused=(),
        revocations=(),
        index_key_id="K_IDX",
    )
    snap = IndexSnapshot(verified=verified, refusal=None, as_of=datetime(2026, 11, 25, tzinfo=timezone.utc), degraded=False, fetched_at=None, stale=False)
    cache = SimpleNamespace(
        snapshot=lambda: snap,
        revocations=store,
        revoked_sets=lambda _v: (frozenset(), frozenset({"acme/rev@1.0.0"})),
    )

    with pytest.raises(HTTPException) as exc1:
        catalog_install_support.resolve_item(snap, "acme/rev", cache=cache)
    assert exc1.value.status_code == 409
    assert exc1.value.detail["code"] == "version_revoked"

    verified_key = VerifiedIndex(
        serial=3,
        generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        items=(item,),
        untrusted_items=(),
        refused=(),
        revocations=(),
        index_key_id="K_IDX",
    )
    snap_key = IndexSnapshot(verified=verified_key, refusal=None, as_of=datetime(2026, 11, 25, tzinfo=timezone.utc), degraded=False, fetched_at=None, stale=False)
    cache_key = SimpleNamespace(
        snapshot=lambda: snap_key,
        revocations=store,
        revoked_sets=lambda _v: (frozenset({"KREV"}), frozenset()),
    )
    with pytest.raises(HTTPException) as exc2:
        catalog_install_support.resolve_item(snap_key, "acme/rev", cache=cache_key)
    assert exc2.value.status_code == 409
    assert exc2.value.detail["code"] == "key_untrusted"


@pytest.mark.asyncio
async def test_revocations_refresh_route_notifies_after_pass_and_pushes_catalog_and_cplugs(monkeypatch):
    app = FastAPI()
    app.include_router(catalog_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None

    verified = VerifiedIndex(
        serial=10,
        generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        items=(),
        untrusted_items=(),
        refused=(),
        revocations=(RevocationRef(kind="version", subject="acme/demo@1.0.0", since="2026-11-25T00:00:00Z"),),
        index_key_id="K_IDX",
    )
    snap = IndexSnapshot(
        verified=verified,
        refusal=None,
        as_of=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        fetched_at=100.0,
        stale=False,
    )
    events: List[str] = []

    class _FakeCache:
        async def refresh_now(self):
            events.append("refresh")
            return snap, True

        def snapshot(self):
            return snap

        def revoked_sets(self, _v):
            return (frozenset({"K99"}), frozenset({"acme/demo@1.0.0"}))

    async def fake_notify(_snap):
        events.append("notify_after_pass")

    app.state.catalog_index_refresher = SimpleNamespace(notify_after_pass=fake_notify)
    app.state.services = SimpleNamespace(
        catalog=SimpleNamespace(
            index_cache=_FakeCache(),
        )
    )
    pushed: List[str] = []
    monkeypatch.setattr(resource_push, "notify", lambda topic: pushed.append(topic))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/catalog/revocations/refresh")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["serial"] == 10
    assert body["revoked_keys"] == ["K99"]
    assert body["revoked_versions"] == ["acme/demo@1.0.0"]
    assert "refresh" in events and "notify_after_pass" in events
    assert "catalog" in pushed and "cplugs" in pushed


def test_github_catalog_items_uses_snapshot_and_blocks_revoked_repos():
    item = _item("acme/evil", "1.0.0", "K1")
    prov = UpstreamProvenance(source_type="github", repo="evil-owner/evil-repo", tag="v1.0.0", commit_sha="a" * 40, signature_verified=True)
    item = item.model_copy(update={"versions": [item.versions[0].model_copy(update={"provenance": prov})]})
    verified = VerifiedIndex(
        serial=5,
        generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        items=(item,),
        untrusted_items=(),
        refused=(),
        revocations=(RevocationRef(kind="version", subject="acme/evil@1.0.0", since="2026-11-25T00:00:00Z"),),
        index_key_id="K_IDX",
    )
    snap = IndexSnapshot(verified=verified, refusal=None, as_of=datetime(2026, 11, 25, tzinfo=timezone.utc), degraded=False, fetched_at=None, stale=False)
    cache = SimpleNamespace(
        snapshot=lambda: snap,
        revocations=None,
        revoked_sets=lambda _v: (frozenset(), frozenset({"acme/evil@1.0.0"})),
    )
    req = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(catalog=SimpleNamespace(index_cache=cache))))
    )
    items = github_install_support.catalog_items_from_app(req)
    assert len(items) == 1 and items[0].id == "acme/evil"

    with pytest.raises(HTTPException) as exc:
        github_install_support.check_revoked_github_install(req, "evil-owner/evil-repo")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "version_revoked"


@pytest.mark.asyncio
async def test_supervisor_revokes_tier0_and_cplug_row_exposes_revoked_and_allows_disable(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    code_dir = state_dir / "plugins" / "tierzero"
    code_dir.mkdir(parents=True)
    (code_dir / "carnivore.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "id": "tierzero",
                "name": "TierZero",
                "version": "1.0.0",
                "kind": "plugin",
                "description": "Tier 0 plugin",
                "author": "acme",
                "tier": "catalog",
            }
        ),
        encoding="utf-8",
    )
    manifest = load_sidecar_manifest(code_dir, "tierzero")
    defn = SidecarDefinition(
        manifest=manifest,
        item_id="acme/tierzero",
        install_key="k1",
        code_root=code_dir,
        folder=state_dir / "data",
    )
    owner_switch.write(state_dir, True)
    owner_state.update(
        state_dir,
        manifest,
        None,
        lambda st: replace(st, enabled=True, digest=manifest.code_digest),
    )

    sup = Supervisor(
        state_dir=state_dir,
        app_version="1.0.0",
        dispatcher=SimpleNamespace(),
        alert=lambda *_a: None,
        cancel_side_effects=lambda *_a: {},
        activity=lambda *_a: None,
        index={
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "expires_at": "2099-01-01T00:00:00Z",
            "revoked": [],
        },
    )
    spec = PluginSpec(
        ctx=PluginContext(
            plugin_id="tierzero",
            install_key="k1",
            tier="catalog",
            data_dir=state_dir / "data",
            granted=frozenset(),
        ),
        code_dir=code_dir,
        entry="",
        version="1.0.0",
        code_digest=manifest.code_digest,
        tier0=True,
        catalog_id="acme/tierzero",
    )
    state = await sup.activate(spec)
    assert state == TIER0_STATE

    await sup.set_index({"generated_at": "2026-11-25T00:00:00Z", "revoked": [{"id": "acme/tierzero", "version": "1.0.0"}]})
    assert sup.state("tierzero") == "revoked"
    assert "tierzero" in sup._revoked

    fake_live = SimpleNamespace(
        supervisor=sup,
        safe_mode=lambda: {"env": False, "owner": False},
        _catalog_cache=lambda: None,
    )
    fake_app = SimpleNamespace(state=SimpleNamespace(sidecar_runtime=fake_live))
    host = host_runtime.Host(state_dir, app=fake_app)
    row = host_routes.cplug_row(host, defn)
    assert row["revoked"] is True
    assert row["state"] == "unavailable"
    assert row["revocation_reason"] == "revoked_in_index"


def test_flagged_ack_alias_views_and_default_installs_guard(tmp_path: Path, monkeypatch):
    c1 = InstallConsent(digest="d" * 64, body_sha="b" * 64, acknowledge_flagged=True)
    assert catalog_cplug_gates.flagged_ack_given(c1) is True
    u1 = UpdateConsent(digest="d" * 64, body_sha="b" * 64, acknowledge_flagged=True)
    assert catalog_cplug_gates.flagged_ack_given(u1) is True
    c0 = InstallConsent(digest="d" * 64, body_sha="b" * 64)
    assert catalog_cplug_gates.flagged_ack_given(c0) is False

    flagged_item = _item("acme/flagged", "1.0.0", "K1", flagged=True)
    snap = IndexSnapshot(
        verified=VerifiedIndex(
            serial=7,
            generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
            degraded=False,
            items=(flagged_item,),
            untrusted_items=(),
            refused=(),
            revocations=(RevocationRef(kind="version", subject="acme/flagged@1.0.0", since="2026-11-25T00:00:00Z"),),
            index_key_id="K_IDX",
        ),
        refusal=None,
        as_of=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        fetched_at=None,
        stale=False,
    )
    view = catalog_views.item_view(flagged_item, installed=None, snapshot=snap, untrusted=False)
    assert view.flagged is True
    assert view.requires_warning_ack is True
    assert view.warning_reasons == ["network: outbound host"]
    assert view.review == {"status": "reviewed", "verdict": "flagged", "summary": "Needs outbound call", "model": None, "override": None, "reviewed_at": None, "warnings": None} or (view.review and view.review["verdict"] == "flagged" and view.review["summary"] == "Needs outbound call")
    assert view.revoked is True
    assert view.versions[0]["flagged"] is True
    assert view.versions[0]["revoked"] is True

    class _LedgerCtx:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def find(self, *_a):
            return None

    req = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(catalog=SimpleNamespace(ledger=lambda: _LedgerCtx()))))
    )

    async def fake_snapshot(_r):
        return snap

    async def fake_preview(_r, _b):
        return SimpleNamespace(mod_flagged_ack_needed=False, requires_warning_ack=True, flagged=True)

    called = []
    monkeypatch.setattr(catalog_default_installs, "_snapshot", fake_snapshot)
    monkeypatch.setattr(catalog_default_installs, "resolve_item", lambda *_a: (flagged_item, flagged_item.versions[0]))
    monkeypatch.setattr(catalog_default_installs, "preview_install", fake_preview)
    monkeypatch.setattr(catalog_default_installs, "run_install", lambda *_a: called.append("installed"))
    out = asyncio.run(catalog_default_installs.install_defaults(req, ids=("acme/flagged",), state_dir=tmp_path))
    assert out == []
    assert called == []


@pytest.mark.asyncio
async def test_put_cplug_disable_succeeds_and_enable_refuses_when_revoked(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    code_dir = state_dir / "plugins" / "revplug"
    code_dir.mkdir(parents=True)
    (code_dir / "carnivore.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "id": "revplug",
                "name": "RevPlug",
                "version": "1.0.0",
                "kind": "plugin",
                "description": "Revocable plugin",
                "author": "acme",
                "tier": "catalog",
            }
        ),
        encoding="utf-8",
    )
    manifest = load_sidecar_manifest(code_dir, "revplug")
    defn = SidecarDefinition(
        manifest=manifest,
        item_id="acme/revplug",
        install_key="inst-revplug",
        code_root=code_dir,
        folder=state_dir / "data",
    )
    owner_switch.write(state_dir, True)
    owner_state.update(state_dir, manifest, None, lambda st: replace(st, enabled=True, digest=manifest.code_digest))

    sup = Supervisor(
        state_dir=state_dir,
        app_version="1.0.0",
        dispatcher=SimpleNamespace(),
        alert=lambda *_a: None,
        cancel_side_effects=lambda *_a: {},
        activity=lambda *_a: None,
        index={
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "expires_at": "2099-01-01T00:00:00Z",
            "revoked": [],
        },
    )
    sup._revoked.add("revplug")
    sup._state["revplug"] = "revoked"
    fake_live = SimpleNamespace(
        supervisor=sup,
        safe_mode=lambda: {"env": False, "owner": False},
        _catalog_cache=lambda: None,
        _all_definitions=lambda: [defn],
        tier0_channels=None,
    )
    app = FastAPI()
    app.include_router(host_routes.host_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.sidecar_runtime = fake_live
    host = host_runtime.Host(state_dir, app=app)
    monkeypatch.setattr(host_routes.runtime, "host_for", lambda _app: host)
    monkeypatch.setattr(host_routes, "_shipped", lambda _cid: defn)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rev = owner_state.get(state_dir, manifest).revision
        off_resp = await client.put("/api/v1/cplugs/revplug", json={"revision": rev, "enabled": False})
        assert off_resp.status_code == 200, off_resp.text
        body = off_resp.json()
        assert body["enabled"] is False
        assert body["revoked"] is True

        on_resp = await client.put("/api/v1/cplugs/revplug", json={"revision": body["revision"], "enabled": True})
        assert on_resp.status_code == 409, on_resp.text
        assert on_resp.json()["detail"]["code"] == "version_revoked"


def test_github_revocation_checks_refused_item_id_untrusted_items_and_dropped_provenance_repo():
    verified_ref = VerifiedIndex(
        serial=5,
        generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        items=(),
        untrusted_items=(),
        refused=(
            ItemRefusal(item_id="acme/dropped", code="version_revoked", detail="version revoked"),
            ItemRefusal(item_id="acme/badkey", code="key_untrusted", detail="key revoked"),
            ItemRefusal(item_id="acme/malformed", code="signature_invalid", detail="item schema: bad"),
        ),
        revocations=(),
        index_key_id="K_IDX",
    )
    snap_ref = IndexSnapshot(
        verified=verified_ref,
        refusal=None,
        as_of=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        fetched_at=None,
        stale=False,
    )
    cache_ref = SimpleNamespace(snapshot=lambda: snap_ref, revocations=None)
    req_ref = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(catalog=SimpleNamespace(index_cache=cache_ref))))
    )

    with pytest.raises(HTTPException) as exc_drop:
        github_install_support.check_revoked_github_install(req_ref, "acme/dropped")
    assert exc_drop.value.status_code == 409
    assert exc_drop.value.detail["code"] == "version_revoked"

    with pytest.raises(HTTPException) as exc_key:
        github_install_support.check_revoked_github_install(req_ref, "acme/badkey")
    assert exc_key.value.status_code == 409
    assert exc_key.value.detail["code"] == "key_untrusted"

    github_install_support.check_revoked_github_install(req_ref, "acme/malformed")

    untrusted_item = _item("acme/untrusted-rev", "1.0.0", "K_BAD")
    prov = UpstreamProvenance(
        source_type="github",
        repo="baduser/bad-repo",
        tag="v1.0.0",
        commit_sha="a" * 40,
        signature_verified=True,
    )
    untrusted_item = untrusted_item.model_copy(update={"versions": [untrusted_item.versions[0].model_copy(update={"provenance": prov})]})
    verified_unt = VerifiedIndex(
        serial=6,
        generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        items=(),
        untrusted_items=(untrusted_item,),
        refused=(),
        revocations=(RevocationRef(kind="key", subject="K_BAD", since="2026-11-25T00:00:00Z"),),
        index_key_id="K_IDX",
    )
    snap_unt = IndexSnapshot(
        verified=verified_unt,
        refusal=None,
        as_of=datetime(2026, 11, 25, tzinfo=timezone.utc),
        degraded=False,
        fetched_at=None,
        stale=False,
    )
    cache_unt = SimpleNamespace(snapshot=lambda: snap_unt, revocations=None)
    req_unt = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(catalog=SimpleNamespace(index_cache=cache_unt))))
    )
    with pytest.raises(HTTPException) as exc_unt:
        github_install_support.check_revoked_github_install(req_unt, "baduser/bad-repo")
    assert exc_unt.value.status_code == 409
    assert exc_unt.value.detail["code"] == "key_untrusted"


def test_verify_index_preserves_provenance_repos_and_index_cache_remembers_sticky_repo_mapping(tmp_path: Path):
    from src.core.catalog.minisign import parse_public_key
    from src.core.catalog.trust_root import TrustRoot
    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from tests.helpers.catalog_fixture import DEFAULT_GENERATED_AT, build_signed_index, revocation_entry, skill_item
    from tests.helpers.minisign_keys import generate_keypair, require_minisign

    require_minisign()
    (tmp_path / "idx").mkdir()
    (tmp_path / "pub").mkdir()
    idx_kp = generate_keypair(tmp_path / "idx")
    pub_kp = generate_keypair(tmp_path / "pub")
    idx_pub = parse_public_key(idx_kp.public_key_text)
    pub_pub = parse_public_key(pub_kp.public_key_text)
    trust_root = TrustRoot(
        index_key=idx_pub,
        publisher_key=pub_pub,
        min_index_serial=1,
        max_serial_jump=100,
        staleness_days=30,
    )

    digest = "d" * 64
    commit = "a" * 40
    raw_item = skill_item(
        "evilplug",
        "acme",
        digest,
        version="1.0.0",
        kind="cplug",
        path="cplugs/acme/evilplug",
        commit=commit,
    )
    raw_item["versions"][0]["manifest_schema"] = 2
    raw_item["versions"][0]["provenance"] = {
        "source_type": "github",
        "repo": "eviluser/evil-repo",
        "tag": "v1.0.0",
        "commit_sha": commit,
        "signature_verified": True,
    }
    rev_block = {
        "keys": [],
        "versions": [
            revocation_entry(
                tmp_path,
                kind="version",
                subject="acme/evilplug@1.0.0",
                since="2026-09-01T00:00:00+00:00",
                keypair=pub_kp,
            )
        ],
    }
    signed = build_signed_index(
        tmp_path,
        index_keypair=idx_kp,
        publisher_keypair=pub_kp,
        items=[raw_item],
        serial=1,
        generated_at=DEFAULT_GENERATED_AT,
        revocations=rev_block,
        publisher_handle="acme",
    )

    verified = verify_index(
        signed.index_bytes,
        signed.minisig_text,
        trust_root=trust_root,
        seen_revocations=frozenset(),
        last_verified_serial=0,
        now=DEFAULT_GENERATED_AT,
    )
    assert isinstance(verified, VerifiedIndex)
    assert verified.items == ()
    assert len(verified.refused) == 1
    assert verified.refused[0].item_id == "acme/evilplug"
    assert verified.refused[0].code == "version_revoked"
    assert verified.refused[0].provenance_repos == ("eviluser/evil-repo",)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ensure_db_migrated(state_dir)
    clock = SimpleNamespace(now=lambda: 1764032400.0, monotonic=lambda: 100.0)
    cache = IndexCache(
        index_url=lambda: "https://index.example/v1",
        trust_root=trust_root,
        clock=clock,
        open_db=lambda: connect(db_path_for(state_dir)),
    )
    cache._persist(verified, None)
    cache._record_repo_mappings(verified)
    snap_dropped = IndexSnapshot(
        verified=verified,
        refusal=None,
        as_of=verified.generated_at,
        degraded=False,
        fetched_at=None,
        stale=False,
    )
    cache._snapshot = snap_dropped
    req = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(catalog=SimpleNamespace(index_cache=cache))))
    )

    with pytest.raises(HTTPException) as exc_pre:
        github_install_support.check_revoked_github_install(req, "eviluser/evil-repo")
    assert exc_pre.value.status_code == 409
    assert exc_pre.value.detail["code"] == "version_revoked"

    with pytest.raises(HTTPException) as exc_post:
        github_install_support.check_revoked_github_install(req, "eviluser/evil-repo", name="evilplug", raw_id="evilplug")
    assert exc_post.value.status_code == 409
    assert exc_post.value.detail["code"] == "version_revoked"

    empty_later = VerifiedIndex(
        serial=2,
        generated_at=datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc),
        degraded=False,
        items=(),
        untrusted_items=(),
        refused=(),
        revocations=(),
        index_key_id=idx_pub.key_id,
    )
    cache._snapshot = IndexSnapshot(
        verified=empty_later,
        refusal=None,
        as_of=empty_later.generated_at,
        degraded=False,
        fetched_at=None,
        stale=False,
    )
    assert cache.item_ids_for_repo("eviluser/evil-repo") == ("acme/evilplug",)
    with pytest.raises(HTTPException) as exc_sticky:
        github_install_support.check_revoked_github_install(req, "eviluser/evil-repo")
    assert exc_sticky.value.status_code == 409
    assert exc_sticky.value.detail["code"] == "version_revoked"
