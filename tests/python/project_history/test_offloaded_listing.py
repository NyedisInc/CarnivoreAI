from src.core.project_history import build_history
from src.core.project_history.query import HistoryQuery, RowFacts

PROJECTS = [{"id": 1, "display_name": "alpha", "root": "/x/alpha", "archived_at": None}]


def _row(uuid: str, conversation: str, archived: bool = False) -> dict:
    return {"session_uuid": uuid, "project_id": 1, "lifecycle": "stopped", "lifecycle_source": "import", "origin": "imported", "kind": "interactive",
            "claude_session_uuid": conversation, "archived_at": "2026-09-08T00:00:00Z" if archived else None,
            "created_at": "2026-10-01T00:00:00Z", "last_work_at": "2026-10-02T00:00:00Z"}


def _uuids(query: HistoryQuery, rows: list) -> list:
    facts = RowFacts(family_of=lambda r: None, offloaded=frozenset({"c-off"}))
    groups = build_history(PROJECTS, rows, query, facts)["groups"]
    return [s["session_uuid"] for g in groups for s in g["sessions"]]


def test_an_offloaded_row_with_no_family_passes_the_claude_filter_and_says_claude() -> None:
    rows = [_row("s-off", "c-off"), _row("s-other", "c-other")]
    assert _uuids(HistoryQuery.parse(state="closed,unknown", agent="claude,codex"), rows) == ["s-off"]
    group = build_history(PROJECTS, rows, HistoryQuery.parse(agent="claude"), RowFacts(family_of=lambda r: None, offloaded=frozenset({"c-off"})))["groups"][0]
    assert [s["agent_family"] for s in group["sessions"]] == ["claude"]


def test_a_removed_offloaded_row_is_listed_when_the_read_asks_for_offloaded_rows() -> None:
    rows = [_row("s-off", "c-off", archived=True), _row("s-plain", "c-other", archived=True)]
    plain = HistoryQuery.parse(state="closed,unknown", agent="claude,codex")
    assert _uuids(plain, rows) == []
    assert _uuids(HistoryQuery.parse(state="closed,unknown", agent="claude,codex", offloaded=True), rows) == ["s-off"]
