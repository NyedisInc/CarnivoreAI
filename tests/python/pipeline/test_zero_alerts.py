
from contextlib import closing
from pathlib import Path

import pytest

from src.core.app_alerts import service
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.pipeline import log as pipeline_log
from src.core.transcript_manifest import condition

from tests.python.transcript_source.helpers import CONV, WORKDIR


@pytest.fixture()
def world(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    db = db_path_for(state)
    with closing(connect(db, create=False)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, origin, "
            "lifecycle, claude_session_uuid, agent_type, agent_family, created_at, updated_at) VALUES "
            "('sess-uuid-1','cloude','cloude_a',111,?,'created','stopped',?,'claude','claude','2026-09-01','2026-09-01')",
            (WORKDIR, CONV))
    service.configure(db, None)
    pipeline_log.reset()
    yield state, db
    service.configure(None, None)


def _open_keys(db: Path) -> list:
    return sorted(r["key"] for r in service.list_view(db, include_closed=False, limit=100)["alerts"])


def test_boot_closes_open_rows_of_removed_kinds_and_keeps_backup_alerts(world):
    state, db = world
    kw = dict(source="x", severity="error", title_key="app_alert.x.title", db_path=db)
    removed = ["pipeline.stage_dead.milestones", "pipeline.llm_all_down", "transcripts.manifest", "backup_health.plugin.stats"]
    for key in removed:
        assert service.raise_alert(key, **kw) is not None
    service.raise_alert("backup_health.usb_backup", **kw)
    assert len(_open_keys(db)) == 5
    condition.install(state)
    try:
        assert _open_keys(db) == ["backup_health.usb_backup"]
    finally:
        condition.uninstall()


def test_repeats_of_one_failure_are_summarized_once_per_window(caplog):
    now = [0.0]
    assert pipeline_log.log_error("e", plugin="p", error=ValueError("a"), clock=lambda: now[0]) is True
    assert pipeline_log.log_error("e", plugin="p", error=ValueError("b"), clock=lambda: now[0]) is False
    assert pipeline_log.log_error("e", plugin="q", error=ValueError("b"), clock=lambda: now[0]) is True
    now[0] = pipeline_log.SUMMARY_WINDOW_SECONDS + 1
    assert pipeline_log.log_error("e", plugin="p", error=ValueError("c"), clock=lambda: now[0]) is True
    pipeline_log.reset()
