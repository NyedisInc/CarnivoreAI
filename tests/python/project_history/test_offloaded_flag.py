from src.core.project_history import build_history
from src.core.project_history.query import HistoryQuery, RowFacts

PROJECTS = [{"id": 1, "display_name": "alpha", "root": "/x/alpha", "archived_at": None}]


def _row(uuid: str, conversation: str) -> dict:
    return {"session_uuid": uuid, "project_id": 1, "lifecycle": "stopped", "lifecycle_source": "tmux_missing", "claude_session_uuid": conversation,
            "created_at": "2026-10-01T00:00:00Z", "last_work_at": "2026-10-02T00:00:00Z"}


def _sessions(facts: RowFacts) -> dict:
    rows = [_row("s-off", "c-off"), _row("s-disk", "c-disk"), _row("s-gone", "c-gone")]
    group = build_history(PROJECTS, rows, HistoryQuery.parse(), facts)["groups"][0]
    return {s["session_uuid"]: s for s in group["sessions"]}


def test_only_a_marked_conversation_with_no_transcript_on_disk_is_offloaded() -> None:
    got = _sessions(RowFacts(family_of=lambda r: "claude", transcripts=frozenset({"c-disk"}), offloaded=frozenset({"c-off", "c-disk"})))
    assert (got["s-off"]["offloaded"], got["s-off"]["has_transcript"]) == (True, False)
    assert got["s-disk"]["offloaded"] is False and got["s-disk"]["has_transcript"] is True
    assert got["s-gone"]["offloaded"] is False
