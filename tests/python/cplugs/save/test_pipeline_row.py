
from __future__ import annotations

import asyncio
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import pipeline_plugin_routes
from src.api.auth import require_auth
from src.core.pipeline import runtime
from src.cplugs import save as save_plugin
from src.cplugs.save import capture_hook, pipeline_row, pipeline_seed, scheduler
from src.cplugs.save.vault.follow import SliceResult
from src.cplugs.sdk import pipeline_rows
from tests.python.time_machine.helpers import make_corpus

ROW_KEYS = {"plugin", "kind", "scope", "session_uuid", "session", "project_id", "project", "conversation_id", "family",
            "trigger", "finished_at", "duration_ms", "runs", "events", "outcome", "error", "seeded", "detail"}


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    runtime.reset_for_test()
    pipeline_rows._providers.clear()
    pushes: list = []
    monkeypatch.setattr("src.core.pipeline.engine.push_status", lambda: pushes.append(1))
    record = pipeline_row.BackupsRecord(wall=lambda: 1000.0)
    monkeypatch.setattr(pipeline_row, "RECORD", record)
    monkeypatch.setattr(scheduler, "RECORD", record)
    monkeypatch.setattr(capture_hook, "RECORD", record)
    monkeypatch.setattr(save_plugin.tf, "state_dir", lambda: tmp_path / "state")
    yield pushes
    pipeline_rows._providers.clear()


def test_with_no_provider_the_status_has_no_backups_row(clean):
    assert runtime.status() == {"state": "off"}


def test_a_registered_row_joins_recent_and_unregistering_removes_it(clean):
    pipeline_row.RECORD.record_pass(written=2, failed=0, duration_s=0.5)
    pipeline_row.register()
    [row] = runtime.status()["recent"]
    assert set(row) == ROW_KEYS | {"contributor"}
    assert (row["plugin"], row["scope"], row["runs"], row["events"], row["duration_ms"], row["finished_at"], row["outcome"]) == \
        ("backups", "plugin", 1, 2, 500.0, 1000.0, "ok")
    pipeline_row.unregister()
    assert "recent" not in runtime.status()


def test_register_unregister_and_each_record_push_the_pipeline_topic(clean):
    pipeline_row.register()
    after_register = len(clean)
    assert after_register >= 1
    pipeline_row.RECORD.record_capture(failed=False, duration_s=0.1)
    assert len(clean) == after_register + 1
    pipeline_row.unregister()
    assert len(clean) == after_register + 2


def test_the_route_serves_the_row_only_while_registered(clean):
    app = FastAPI()
    app.include_router(pipeline_plugin_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    pipeline_row.RECORD.record_capture(failed=False, duration_s=0.1)
    client = TestClient(app)
    assert client.get("/pipeline/status").json().get("recent", []) == []
    pipeline_row.register()
    assert [r["plugin"] for r in client.get("/pipeline/status").json()["recent"]] == ["backups"]


def test_no_row_before_the_first_run(clean):
    assert pipeline_row.RECORD.rows() == []


def test_passes_and_captures_are_counted_and_events_are_the_last_passs_written(clean):
    record = pipeline_row.RECORD
    record.record_pass(written=3, failed=0, duration_s=0.2)
    record.record_capture(failed=False, duration_s=0.05)
    record.record_pass(written=1, failed=0, duration_s=0.3)
    [row] = record.rows()
    assert (row.runs, row.events, row.duration_ms, row.outcome, row.error) == (3, 1, 300.0, "ok", None)


def test_a_failed_pass_or_capture_turns_the_row_red_until_the_next_one_of_its_kind_succeeds(clean):
    record = pipeline_row.RECORD
    record.record_pass(written=0, failed=2, duration_s=0.1)
    assert (record.rows()[0].outcome, record.rows()[0].error) == ("failed", "capture_failed")
    record.record_capture(failed=False, duration_s=0.1)
    assert record.rows()[0].outcome == "failed"
    record.record_pass(written=1, failed=0, duration_s=0.1)
    assert record.rows()[0].outcome == "ok"
    record.record_capture(failed=True, duration_s=0.1)
    assert record.rows()[0].outcome == "failed"
    record.record_capture(failed=False, duration_s=0.1)
    record.record_pass(written=0, failed=0, duration_s=0.0, error="OSError")
    assert (record.rows()[0].outcome, record.rows()[0].error) == ("failed", "OSError")


def test_a_slice_counts_a_failed_capture(clean):
    follower = scheduler.Follower(slice_fn=lambda: SliceResult(captured=2, failed=1))
    assert asyncio.run(follower.once()).failed == 1
    [row] = pipeline_row.RECORD.rows()
    assert (row.runs, row.events, row.outcome) == (1, 2, "failed")


def test_the_follower_records_its_slice(clean):
    follower = scheduler.Follower(slice_fn=lambda: SliceResult(captured=1))
    assert asyncio.run(follower.once()).captured == 1
    [row] = pipeline_row.RECORD.rows()
    assert (row.runs, row.events, row.outcome) == (1, 1, "ok")


def test_the_plugin_start_offers_the_row_and_the_stop_withdraws_it(clean):
    async def cycle():
        await save_plugin._start(None)
        offered = "save" in pipeline_rows._providers
        await save_plugin._stop(None)
        return offered, "save" in pipeline_rows._providers

    assert asyncio.run(cycle()) == (True, False)


def _tree(tmp_path, convs=3, size=10):
    root = tmp_path / "state" / "vault"
    for n in range(convs):
        point = root / "manifests" / f"conv{n:03d}abcdef" / "20261014T000000Z-kill.json"
        point.parent.mkdir(parents=True)
        point.write_bytes(b"x" * size)
        os.utime(point, (1000 + n, 1000 + n))
    os.utime(point, (5000, 5000))
    (root / "vault-state.json").write_text('{"blob_bytes": 60}')
    return root


def test_the_scan_counts_conversations_and_bytes_and_takes_the_newest_mtime(tmp_path):
    facts = pipeline_seed.scan_vault(_tree(tmp_path))
    assert (facts.newest_at, facts.conversations, facts.size_bytes, facts.truncated) == (5000.0, 3, 60, False)


def test_the_scan_of_a_missing_or_empty_vault_has_nothing_to_show(tmp_path):
    assert pipeline_seed.scan_vault(tmp_path / "none").newest_at is None
    (tmp_path / "empty").mkdir()
    assert pipeline_seed.scan_vault(tmp_path / "empty").newest_at is None


def test_the_scan_is_bounded_by_its_entry_cap_and_its_time_budget(tmp_path):
    root = _tree(tmp_path, convs=5)
    assert pipeline_seed.scan_vault(root, limit=4).truncated is True
    ticks = iter(range(0, 1000))
    assert pipeline_seed.scan_vault(root, clock=lambda: next(ticks), budget=2).truncated is True


def test_a_seeded_row_shows_at_once_with_the_disk_time_and_no_measured_run(tmp_path, clean):
    assert pipeline_row.seed_from_disk(_tree(tmp_path)) is True
    pipeline_row.register()
    [row] = runtime.status()["recent"]
    assert (row["finished_at"], row["duration_ms"], row["runs"], row["seeded"], row["outcome"]) == (5000.0, None, None, True, "ok")
    assert row["detail"] == {"conversations": 3, "size_bytes": 60}


def test_the_first_measured_run_replaces_the_seed(tmp_path, clean):
    state = _tree(tmp_path)
    pipeline_row.seed_from_disk(state)
    pipeline_row.RECORD.record_capture(failed=False, duration_s=0.25)
    [row] = pipeline_row.RECORD.rows()
    assert (row.finished_at, row.duration_ms, row.runs, row.seeded, row.detail) == (1000.0, 250.0, 1, False, None)
    assert pipeline_row.seed_from_disk(state) is False


def test_an_empty_vault_leaves_no_row(tmp_path, clean):
    assert pipeline_row.seed_from_disk(tmp_path / "state" / "vault") is False
    assert pipeline_row.RECORD.rows() == []


def test_the_plugin_start_seeds_the_row_so_it_shows_at_once(tmp_path, clean):
    _tree(tmp_path)

    async def start():
        await save_plugin._start(None)
        rows = runtime.status()["recent"]
        await save_plugin._stop(None)
        return rows

    [row] = asyncio.run(start())
    assert (row["plugin"], row["seeded"], row["duration_ms"], row["runs"]) == ("backups", True, None, None)


def test_a_contributed_row_names_the_plugin_that_offered_it():
    from src.cplugs.sdk import pipeline_rows
    row = pipeline_rows.PipelineRow(plugin="backups", finished_at=1.0, duration_ms=None, runs=None)
    pipeline_rows._providers["save-test"] = lambda: [row]
    try:
        assert [r["contributor"] for r in pipeline_rows.rows() if r["plugin"] == "backups"] == ["save-test"]
    finally:
        pipeline_rows._providers.pop("save-test", None)
