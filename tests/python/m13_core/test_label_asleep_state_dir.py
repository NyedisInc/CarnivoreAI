from contextlib import closing
from pathlib import Path

from src.config import settings
from src.core import session_sleep
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.sessions.label_asleep import set_asleep_label

UUID = "5ab0c0de-0000-4000-8000-0000000000cc"


def test_label_found_through_the_injected_state_dir_not_the_global_one(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: elsewhere)
    monkeypatch.setattr(session_sleep, "_transcript_absent", lambda row, uuid_: False)
    with closing(connect(db_path_for(state))) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, tmux_created_epoch, lifecycle, "
            "lifecycle_source, project_attribution, working_dir, agent_family, claude_session_uuid, "
            "created_at, updated_at) VALUES ('su-1','created','cloude','carnivore_x',1,'stopped','slept_by_user',"
            "'explicit','/tmp','claude',?, '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')", (UUID,))
        conn.commit()
    assert set_asleep_label("su-1", "build bot", state_dir=state) == ("su-1", "carnivore_x")
