
import json
from datetime import datetime, timezone

import pytest

from src.core.attention.transcript_facts import FACTS_TAIL_BYTES, read_transcript_facts
from src.core.mcp_health.fold import STATE_FAILED, fold_mcp_health
from src.core.mcp_health.history import reset_history, scan_mcp_events

STARTED = datetime(2026, 10, 10, 11, 50, tzinfo=timezone.utc)
FAILED = {"type": "attachment", "timestamp": "2026-10-12T15:07:33.148Z", "attachment": {
    "type": "deferred_tools_delta", "addedNames": [], "removedNames": [], "pendingMcpServers": [],
    "failedMcpServers": [{"name": "carnivore", "errorCode": "ECONNREFUSED", "error": "ECONNREFUSED"},
                         {"name": "imageserver", "errorCode": "ENDPOINT_NOT_FOUND", "error": "x"}]}}
RECONNECTED = {"type": "user", "timestamp": "2026-10-12T16:00:00.000Z", "message": {
    "role": "user", "content": "<local-command-stdout>Reconnected to carnivore.</local-command-stdout>"}}


def _filler(i: int) -> dict:
    return {"type": "user", "timestamp": "2026-10-12T15:08:%02d.000Z" % (i % 60), "message": {
        "role": "user", "content": "x" * 2000}}


def _write(path, records) -> None:
    with open(path, "a") as handle:
        for r in records:
            handle.write(json.dumps(r) + "\n")


def _drops(path):
    facts = read_transcript_facts(str(path))
    health = fold_mcp_health(facts.mcp_events, since=STARTED, window_from=facts.mcp_window_from)
    return None if health is None else {d.name: d.state for d in health.dropped}


@pytest.fixture(autouse=True)
def _clean():
    reset_history()
    yield
    reset_history()


def test_failed_record_scrolled_out_of_the_tail_still_shows(tmp_path):
    path = tmp_path / "t.jsonl"
    _write(path, [FAILED] + [_filler(i) for i in range(FACTS_TAIL_BYTES // 2000 * 3)])
    assert path.stat().st_size > 2 * FACTS_TAIL_BYTES
    assert _drops(path) == {"carnivore": STATE_FAILED, "imageserver": STATE_FAILED}


def test_it_survives_more_passes_and_clears_on_a_later_reconnect_line(tmp_path):
    path = tmp_path / "t.jsonl"
    _write(path, [FAILED] + [_filler(i) for i in range(FACTS_TAIL_BYTES // 2000 * 3)])
    assert _drops(path) is not None
    _write(path, [_filler(i) for i in range(FACTS_TAIL_BYTES // 2000 * 2)])
    assert _drops(path) == {"carnivore": STATE_FAILED, "imageserver": STATE_FAILED}
    _write(path, [RECONNECTED])
    assert _drops(path) == {"imageserver": STATE_FAILED}


def test_a_replaced_shorter_file_forgets_the_old_one(tmp_path):
    path = tmp_path / "t.jsonl"
    _write(path, [FAILED] + [_filler(i) for i in range(FACTS_TAIL_BYTES // 2000 * 3)])
    assert _drops(path) is not None
    path.write_text(json.dumps(_filler(1)) + "\n")
    assert _drops(path) is None


def test_scan_skips_a_partial_first_line_and_never_raises(tmp_path):
    path = tmp_path / "t.jsonl"
    _write(path, [FAILED, _filler(1)])
    size = path.stat().st_size
    assert len(scan_mcp_events(str(path), 0, size)) == 1
    assert scan_mcp_events(str(path), 5, size) == ()
    assert scan_mcp_events(str(tmp_path / "missing.jsonl"), 0, 100) == ()
