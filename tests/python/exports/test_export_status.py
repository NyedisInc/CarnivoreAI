
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import exports_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.deepsearch import grouped, hit_exports
from src.core.deepsearch.cache import db as cache_db
from src.core.exports import store
from src.core.federation import peer_deepsearch
from src.core.resource_push import topics
from tests.python.deepsearch.helpers import build_world, drain, go_ready, scan, teardown
from tests.python.transcript_source.helpers import CONV

SHA = "ab" * 32
CODEX = "0b984f74-cd8c-44ce-8b76-d8a10b8f7ab7"


@pytest.fixture
def h(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    named: List[str] = []
    monkeypatch.setattr(store.resource_push, "notify", named.append)
    monkeypatch.setattr(exports_routes, "_db_path", lambda: db_path_for(state))
    app = FastAPI()
    app.include_router(exports_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    conn = connect(db_path_for(state), create=False)
    yield SimpleNamespace(conn=conn, client=TestClient(app), named=named, state=state, app=app)
    conn.close()


def _bundle(bundle_id: str = "crate-1", **kw) -> store.Bundle:
    return store.Bundle(bundle_id=bundle_id, sha256=kw.pop("sha256", SHA), scope=kw.pop("scope", "session"),
                        created_at=kw.pop("created_at", 1_700_000_000.0), **kw)


def test_the_topic_is_advertised():
    assert topics.EXPORTS == "exports" and topics.EXPORTS in topics.RESOURCE_TOPICS


def test_a_bundle_and_its_pointers_round_trip(h):
    locations = (store.Location("/Volumes/ExampleDrive/crates", 1_700_000_100.0), store.Location("remote:crates"))
    stored = store.record_bundle(h.conn, _bundle(project_uid="p-uid", session_uuid="s-uuid", label="october", locations=locations,
                                                  verified_at=1_700_000_200.0),
                                 [store.Pointer(CONV, "claude", "crate-1", 1_700_000_050.0, "wombat work"),
                                  store.Pointer(CODEX, "codex", "crate-1", 1_700_000_050.0, None)])
    assert (stored.bundle_id, stored.sha256, stored.scope, stored.label, stored.conversations) == ("crate-1", SHA, "session", "october", 2)
    assert stored.locations == locations and stored.local_removed is False and stored.verified_at == 1_700_000_200.0
    assert store.bundle(h.conn, "crate-1") == stored and store.list_bundles(h.conn) == [stored]
    assert store.pointer(h.conn, CONV) == store.Pointer(CONV, "claude", "crate-1", 1_700_000_050.0, "wombat work")
    assert store.pointer(h.conn, CODEX, "codex").family == "codex" and store.pointer(h.conn, CODEX, "claude") is None
    assert set(store.pointers_for(h.conn, [CONV, CODEX, "never-exported"])) == {CONV, CODEX}
    updated = store.update_bundle(h.conn, "crate-1", locations=(store.Location("/elsewhere"),), verified_at=1_700_000_300.0, local_removed=True)
    assert updated.local_removed is True and updated.locations == (store.Location("/elsewhere"),) and updated.verified_at == 1_700_000_300.0
    kept = store.update_bundle(h.conn, "crate-1", verified_at=1_700_000_400.0)
    assert kept.local_removed is True and kept.locations == (store.Location("/elsewhere"),)


def test_a_conversation_points_at_its_newest_bundle_and_an_older_export_never_replaces_it(h):
    store.record_bundle(h.conn, _bundle("crate-old", created_at=1.0), [store.Pointer(CONV, "claude", "crate-old", 100.0, "first")])
    store.record_bundle(h.conn, _bundle("crate-new", created_at=2.0), [store.Pointer(CONV, "claude", "crate-new", 200.0, "second")])
    assert store.pointer(h.conn, CONV).bundle_id == "crate-new"
    store.record_bundle(h.conn, _bundle("crate-older", created_at=0.5), [store.Pointer(CONV, "claude", "crate-older", 50.0, "third")])
    assert store.pointer(h.conn, CONV).bundle_id == "crate-new"
    counts = {b.bundle_id: b.conversations for b in store.list_bundles(h.conn)}
    assert counts == {"crate-new": 1, "crate-old": 0, "crate-older": 0}
    assert [b.bundle_id for b in store.list_bundles(h.conn)] == ["crate-new", "crate-old", "crate-older"]


@pytest.mark.parametrize("bundle,pointer,needle", [
    (dict(bundle_id="x"), None, "bundle id"), (dict(bundle_id="has space"), None, "bundle id"),
    (dict(sha256="XYZ"), None, "sha256"), (dict(sha256="AB" * 32), None, "sha256"), (dict(scope="machine"), None, "scope"),
    (dict(locations=(store.Location(""),)), None, "location"),
    ({}, dict(family="gemini"), "family"), ({}, dict(conversation_id=" "), "conversation id"), ({}, dict(bundle_id="other-bundle"), "bundle it is recorded with"),
])
def test_a_bad_bundle_or_pointer_is_refused_and_nothing_is_written(h, bundle, pointer, needle):
    pointers = [store.Pointer(**{"conversation_id": CONV, "family": "claude", "bundle_id": "crate-1", "exported_at": 1.0, **(pointer or {})})] if pointer is not None else []
    with pytest.raises(store.InvalidExport, match=needle):
        store.record_bundle(h.conn, _bundle(**bundle) if "bundle_id" not in bundle else store.Bundle(
            **{"bundle_id": "crate-1", "sha256": SHA, "scope": "session", "created_at": 1.0, **bundle}), pointers)
    assert store.list_bundles(h.conn) == [] and h.named == []


def test_update_of_an_unknown_bundle_is_refused(h):
    with pytest.raises(store.BundleNotFound):
        store.update_bundle(h.conn, "no-such-bundle", local_removed=True)
    assert h.named == []


def test_every_writer_names_the_exports_topic_after_its_commit(h):
    store.record_bundle(h.conn, _bundle(), [store.Pointer(CONV, "claude", "crate-1", 1.0)])
    assert h.named == ["exports"]
    store.update_bundle(h.conn, "crate-1", verified_at=5.0)
    assert h.named == ["exports", "exports"]


def test_no_module_but_the_store_writes_the_export_tables():
    root = Path(__file__).resolve().parents[3] / "src"
    pattern = re.compile(r"(INSERT\s+(OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO)\s+export_(bundles|pointers)\b", re.I)
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if p.name not in ("store.py", "ddl.py") and pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
    assert pattern.search("conn.execute('UPDATE export_pointers SET title = 1')")


def test_both_routes_need_the_bearer(h):
    del h.app.dependency_overrides[require_auth]
    assert h.client.get("/api/v1/exports").status_code in (401, 403)
    assert h.client.get(f"/api/v1/exports/conversations/{CONV}").status_code in (401, 403)


def test_the_routes_answer_the_documented_shapes(h):
    assert h.client.get("/api/v1/exports").json() == {"bundles": [], "count": 0}
    store.record_bundle(h.conn, _bundle(label="october", project_uid="p-uid", locations=(store.Location("/v/crates", 0.0),)),
                        [store.Pointer(CONV, "claude", "crate-1", 1_700_000_050.0, "wombat work")])
    listed = h.client.get("/api/v1/exports").json()
    assert listed["count"] == 1
    (bundle,) = listed["bundles"]
    assert set(bundle) == {"bundle_id", "sha256", "scope", "project_uid", "session_uuid", "label", "created_at", "locations",
                           "verified_at", "local_removed", "conversations"}
    assert bundle["created_at"] == "2023-11-14T22:13:20+00:00" and bundle["conversations"] == 1 and bundle["local_removed"] is False
    assert bundle["locations"] == [{"where": "/v/crates", "verified_at": "1970-01-01T00:00:00+00:00"}]
    one = h.client.get(f"/api/v1/exports/conversations/{CONV}", params={"family": "claude"}).json()
    assert set(one) == {"conversation_id", "family", "title", "exported_at", "bundle"}
    assert one["title"] == "wombat work" and one["bundle"]["bundle_id"] == "crate-1" and one["exported_at"] == "2023-11-14T22:14:10+00:00"
    assert h.client.get(f"/api/v1/exports/conversations/{CONV}").status_code == 200


def test_an_unexported_conversation_is_404_with_a_code_and_a_bad_family_is_422(h):
    gone = h.client.get("/api/v1/exports/conversations/never-exported")
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "export_not_found"
    store.record_bundle(h.conn, _bundle(), [store.Pointer(CONV, "claude", "crate-1", 1.0)])
    assert h.client.get(f"/api/v1/exports/conversations/{CONV}", params={"family": "codex"}).status_code == 404
    assert h.client.get(f"/api/v1/exports/conversations/{CONV}", params={"family": "gemini"}).status_code == 422


def test_a_deep_search_result_carries_exported_and_a_paired_computer_is_never_sent_it(tmp_path, monkeypatch):
    world = build_world(tmp_path, monkeypatch)
    try:
        scan(world)
        drain(world)
        go_ready(world)
        with closing(cache_db.reader(world["state"])) as conn:
            (before,) = grouped.search_grouped(conn, world["state"], "wombatmain", overrides={})["groups"]
        assert before["exported"] is None
        monkeypatch.setattr(store.resource_push, "notify", lambda _t: None)
        with closing(connect(db_path_for(world["state"]), create=False)) as main:
            store.record_bundle(main, _bundle("crate-7", label="october"), [store.Pointer(CONV, "claude", "crate-7", 1_700_000_050.0, "t")])
        with closing(cache_db.reader(world["state"])) as conn:
            (after,) = grouped.search_grouped(conn, world["state"], "wombatmain", overrides={})["groups"]
        assert after["exported"] == {"bundle_id": "crate-7", "label": "october", "exported_at": "2023-11-14T22:14:10+00:00",
                                     "local_removed": False}
        assert "exported" not in peer_deepsearch.clean_group(after)
    finally:
        teardown()


def test_a_database_without_the_tables_answers_not_exported_instead_of_failing():
    with closing(sqlite3.connect(":memory:")) as conn:
        groups = [{"conversation_id": "c1", "hits": []}]
        hit_exports.attach(conn, groups)
        assert groups[0]["exported"] is None
        hit_exports.attach(conn, [])
