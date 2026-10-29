
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.db import connect, db_path_for
from src.core.deepsearch import hit_exports
from src.core.exports import store
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, project_request, session_request
from tests.python.cplugs.crate.export_extras import HARNESS_VERSION, PLAN_SLUG, add_extras
from tests.python.inventory.world import CONV_A, CONV_A0, UUID_A


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> SimpleNamespace:
    w = make_world(tmp_path_factory.mktemp("crate-roundtrip"))
    w.extras = add_extras(w)
    env = env_for(w)
    named: list = []
    original = store.resource_push.notify
    store.resource_push.notify = named.append
    try:
        w.plans, w.results = {}, {}
        for scope, request in (("project", project_request(w)), ("session", session_request())):
            w.plans[scope] = build_plan(env, request)
            w.results[scope] = run_export(env, w.plans[scope], JobHandle(scope))
    finally:
        store.resource_push.notify = original
    w.named, w.env = named, env
    return w


@pytest.mark.parametrize("scope", ["project", "session"])
def test_full_verify_and_drill_pass(exported: SimpleNamespace, scope: str, tmp_path: Path) -> None:
    result = exported.results[scope]
    assert result.path.is_file() and result.recorded and result.path.name == f"{result.bundle_id}.crate"
    assert Path(f"{result.path}.sha256").read_text().split()[0] == result.sha256
    report = cf.verify(result.path, "drill", expected_sha256=result.sha256, scratch=tmp_path)
    assert report.ok, report.problems
    assert not list(result.path.parent.glob(".*.partial"))


@pytest.mark.parametrize("scope", ["project", "session"])
def test_every_conversation_extracts_byte_exact(exported: SimpleNamespace, scope: str, tmp_path: Path) -> None:
    result, plan = exported.results[scope], exported.plans[scope]
    with cf.open_crate(result.path) as reader:
        ids = [c.id for c in reader.manifest.conversations]
        assert ids == sorted(c["id"] for c in plan.conversations) and CONV_A in ids and CONV_A0 in ids
        by_rel = {r.rel: r for r in reader.files()}
        for conv in ids:
            out = cf.extract_conversation(reader, conv, tmp_path / conv, enc_for=slugify_project_dir)
            for rel in out.files:
                data = (tmp_path / conv / rel).read_bytes()
                source = next(r for r in by_rel.values() if r.conversation_id == conv and r.rel.endswith(Path(rel).name))
                assert hashlib.sha256(data).hexdigest() == source.content_sha256 == hashlib.sha256(
                    Path(source.source_path).read_bytes()).hexdigest()


def test_extras_are_carried_exactly(exported: SimpleNamespace) -> None:
    with cf.open_crate(exported.results["session"].path) as reader:
        by_source = {r.source_path: r for r in reader.files()}
        for name in ("transcript", "tool_result", "no_newline", "big", "binary", "plan"):
            record = by_source[str(exported.extras[name])]
            assert record.content_sha256 == hashlib.sha256(exported.extras[name].read_bytes()).hexdigest(), name
        assert not by_source[str(exported.extras["no_newline"])].ends_with_newline
        assert len(by_source[str(exported.extras["big"])].chunks) >= 3
        assert len(by_source[str(exported.extras["binary"])].chunks) == 3
        assert by_source[str(exported.extras["plan"])].role == "plan" and by_source[str(exported.extras["plan"])].rel == f"plans/{PLAN_SLUG}.md"
        conv = reader.manifest.conversation(CONV_A)
        assert conv.harness_versions == [HARNESS_VERSION] and conv.resume == "claude_resume"
        reconcile = json.loads(reader.read_member("reconcile.json"))["artifacts"]
        assert any(r["status"] == "discovered" and r["what"].endswith(f"{PLAN_SLUG}.md") for r in reconcile)


@pytest.mark.parametrize("scope", ["project", "session"])
def test_rows_match_the_plan_and_secrets_stay_out(exported: SimpleNamespace, scope: str) -> None:
    result, plan = exported.results[scope], exported.plans[scope]
    with cf.open_crate(result.path) as reader:
        tables = reader.tables()
        reconcile = json.loads(reader.read_member("reconcile.json"))["artifacts"]
        rows = {(r["store"], r["what"]): r for r in reconcile if r["kind"] == "rows"}
        for (label, table), planned in plan.row_counts.items():
            row = rows[(label, table)]
            assert row["status"] == "ok" and row["written_count"] == planned or row["status"] == "changed"
        for store_name, table, secret in (("carnivore.db", "spectator_links", {"token_sha256", "link_nonce"}),
                                          ("carnivore.db", "work_item_waits", {"token_hash"})):
            assert secret <= set(tables[store_name][table].omitted_columns), table
            assert all(not (secret & set(line)) for line in reader.rows(store_name, table))
            assert all(c[0] not in secret for c in tables[store_name][table].columns)
        assert "carnivore.db" in tables and all(t.inventory_label for s in tables.values() for t in s.values())


def test_the_record_and_the_exported_status(exported: SimpleNamespace) -> None:
    with closing(connect(db_path_for(exported.state))) as conn:
        for scope, result in exported.results.items():
            bundle = store.bundle(conn, result.bundle_id)
            assert bundle.sha256 == result.sha256 and bundle.verified_at and bundle.locations[0].where == str(result.path)
            own = {c["id"] for c in exported.plans[scope].conversations}
            later = {c["id"] for c in exported.plans["session"].conversations} if scope == "project" else set()
            assert bundle.conversations == len(own - later)
        pointers = store.pointers_for(conn, [CONV_A])
        assert pointers[CONV_A].bundle_id == exported.results["session"].bundle_id
        groups = [{"conversation_id": CONV_A}]
        hit_exports.attach(conn, groups)
        assert groups[0]["exported"]["bundle_id"] == exported.results["session"].bundle_id
    assert exported.named.count("exports") == 2


def test_a_seventy_mib_single_line_exports_byte_exact(tmp_path: Path) -> None:
    w = make_world(tmp_path)
    path = Path(w.home) / "projects" / slugify_project_dir(w.root1) / f"{CONV_A0}.jsonl"
    data = b'{"tool_output":"' + b"y" * (70 * 1024 * 1024) + b'"}\n'
    path.write_bytes(data)
    env = env_for(w)
    result = run_export(env, build_plan(env, session_request(UUID_A)), JobHandle("big"))
    with cf.open_crate(result.path) as reader:
        record = next(r for r in reader.files() if r.source_path == str(path))
        assert record.line_mode and record.length == len(data) and len(record.chunks) == 71
        assert record.content_sha256 == hashlib.sha256(data).hexdigest()
    assert cf.verify(result.path, "full", expected_sha256=result.sha256).ok
