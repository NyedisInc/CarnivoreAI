from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from src.core import claude_session_correlate_ladder as ladder_mod
from src.core import claude_transcript_correlate as correlate_mod
from src.core.db import connect, db_path_for, transaction
from src.core.session_adopt_persist import correlate_after_commit, persist_adoption
from tests.s7_helpers import TEST_SOCKET, listing_of, listing_row, migrated_connection, session_row

WORKING_DIR = "/Users/tester/Development/widget"
NAME = "cloudem8test_offlock"
EPOCH = 1_800_000_000
SESSION_ID = "aaaaaaaa-0000-0000-0000-000000000009"


def test_ladder_is_measured_after_the_claim_transaction_closed(tmp_path: Path, monkeypatch) -> None:
    projects = tmp_path / "projects"
    project_dir = projects / correlate_mod.slugify_project_dir(WORKING_DIR)
    project_dir.mkdir(parents=True)
    (project_dir / f"{SESSION_ID}.jsonl").write_text(json.dumps({
        "type": "user", "isSidechain": False, "timestamp": "2027-01-15T10:00:05Z",
        "sessionId": SESSION_ID, "entrypoint": "cli", "message": {"role": "user", "content": "hi"},
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(correlate_mod, "default_projects_dir", lambda: projects)
    state = tmp_path / "state"
    state.mkdir()
    with closing(migrated_connection(state)):
        pass

    seen: list = []
    real = ladder_mod.correlate_adopted_session_ladder
    conn_box: list = []

    def spy(**kwargs):
        seen.append(conn_box[0].in_transaction)
        return real(**kwargs)

    monkeypatch.setattr(ladder_mod, "correlate_adopted_session_ladder", spy)
    with closing(connect(db_path_for(state))) as conn:
        conn_box.append(conn)
        with transaction(conn):
            result = persist_adoption(
                conn, socket=TEST_SOCKET, name=NAME, correlate=False,
                listing=listing_of([listing_row(NAME, EPOCH, working_dir=WORKING_DIR)]),
            )
        assert result.persisted, result.detail
        assert seen == [], "the ladder ran inside the claim transaction"
        correlate_after_commit(conn, result, socket=TEST_SOCKET, name=NAME, pane_pid=None)
        row = session_row(conn, NAME)
    assert seen == [False]
    assert row["claude_session_uuid"] == SESSION_ID
