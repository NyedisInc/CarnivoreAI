
from datetime import datetime, timedelta, timezone

from src.core.mcp_health.first_hand import (
    GRACE, LINK_CONNECTED, LINK_DROPPED, LINK_UNKNOWN, McpLinkTable, McpSeen,
    apply_carnivore_link, carnivore_state,
)
from src.core.mcp_health.fold import McpDrop, McpHealth

T0 = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def _state(seen, *, started=T0, now=T0 + GRACE + timedelta(seconds=1), expects=True, boot=T0):
    return carnivore_state(seen, started_at=started, now=now, expects_server=expects, boot_at=boot)


def test_state_table():
    inited = McpSeen(initialized_at=T0 + timedelta(seconds=2), requested_at=T0 + timedelta(seconds=2))
    assert _state(inited) == LINK_CONNECTED
    assert _state(None) == LINK_DROPPED
    assert _state(None, now=T0 + GRACE) == LINK_UNKNOWN
    assert _state(None, boot=T0 + timedelta(minutes=5), now=T0 + timedelta(minutes=5, seconds=10)) == LINK_UNKNOWN
    assert _state(None, expects=False) == LINK_UNKNOWN
    assert _state(None, started=None) == LINK_UNKNOWN
    assert _state(McpSeen(initialized_at=T0 - timedelta(hours=1), requested_at=T0 - timedelta(hours=1))) == LINK_DROPPED
    assert _state(McpSeen(requested_at=T0 + timedelta(seconds=5))) == LINK_CONNECTED


def test_table_records_initialize_and_requests_and_is_bounded():
    table = McpLinkTable()
    table.record("t1", "initialize", T0)
    table.record("t1", "tools/list", T0 + timedelta(seconds=9))
    assert table.seen("t1") == McpSeen(initialized_at=T0, requested_at=T0 + timedelta(seconds=9))
    assert table.seen("nope") is None and table.seen(None) is None
    table.record("", "initialize")
    for i in range(4100):
        table.record(f"t{i}", "ping")
    assert len(table._seen) <= 4096


def test_apply_replaces_the_transcripts_word_about_carnivore_only():
    transcript = McpHealth(dropped=(McpDrop("carnivore", "failed", T0, True), McpDrop("linear", "dropped", T0, True)))
    seen = McpSeen(initialized_at=T0, requested_at=T0)
    ok = apply_carnivore_link(transcript, LINK_CONNECTED, seen)
    assert [d.name for d in ok.dropped] == ["linear"] and ok.carnivore.state == LINK_CONNECTED
    unknown = apply_carnivore_link(transcript, LINK_UNKNOWN, None)
    assert [d.name for d in unknown.dropped] == ["linear"]
    assert apply_carnivore_link(None, LINK_UNKNOWN, None) is None
    measured = apply_carnivore_link(None, LINK_CONNECTED, seen)
    assert measured.dropped == () and measured.carnivore.initialized_at == T0
    gone = apply_carnivore_link(None, LINK_DROPPED, None)
    assert [(d.name, d.source, d.exact) for d in gone.dropped] == [("carnivore", "server", True)]
