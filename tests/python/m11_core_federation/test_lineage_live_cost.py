
from __future__ import annotations

from src.core.db import transaction
from src.core.lineage import events, live, scan
from tests.python.lineage.test_live_pass import COMPACT, _transcript, world  # noqa: F401
from tests.s7_helpers import migrated_connection


def test_an_idle_pass_does_not_rewrite_the_cursor(world):  # noqa: F811
    _transcript(world["folder"], "conv-a", [{"type": "user", "entrypoint": "cli"}, COMPACT])
    live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    cursor_file = world["state"] / live.CURSOR_FILENAME
    first = cursor_file.stat().st_mtime_ns
    live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    assert cursor_file.stat().st_mtime_ns == first


def test_reclassifying_switches_reuses_the_passes_own_listing(world, monkeypatch):  # noqa: F811
    conn = migrated_connection(world["state"])
    with transaction(conn):
        events.record_flip_edges(conn, "old", "sess-1", "switch", child_conversation_id="new")
    conn.close()
    _transcript(world["folder"], "new", [{"type": "user", "forkedFrom": {"sessionId": "old", "messageUuid": "m5"}}])

    seen = {}
    real = live.reclassify.reclassify_switches

    def spy(conn, **kwargs):
        seen.update(kwargs)
        return real(conn, **kwargs)

    monkeypatch.setattr(live.reclassify, "reclassify_switches", spy)
    report = live.sweep(world["db"], world["state"], roots=[world["root"]], include_codex=False)
    assert report.counts["switches_reclassified"] >= 1
    assert seen.get("finder") is not None and seen["finder"] is not scan.find_transcript, "a folder walk per edge"
    assert seen["finder"]("new", ()) == world["folder"] / "new.jsonl"
