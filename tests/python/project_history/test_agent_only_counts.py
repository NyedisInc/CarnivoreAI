from src.core.project_history import build_history
from src.core.project_history.query import HistoryQuery, RowFacts

TODAY = "2026-10-13T09:00:00Z"


def _row(uuid, family, **kw):
    base = {"session_uuid": uuid, "project_id": 1, "lifecycle": "running", "lifecycle_source": "tmux",
            "agent_family": family, "created_at": "2026-10-01T00:00:00Z", "last_work_at": TODAY}
    base.update(kw)
    return base


def test_terminals_and_browsers_do_not_count():
    projects = [{"id": 1, "display_name": "alpha", "root": "/x/alpha", "archived_at": None}]
    rows = [_row(f"t{i}", "shell", last_work_at="2026-10-13T20:00:00Z") for i in range(14)]
    rows.append(_row("b", "claude", kind="browser", last_work_at="2026-10-13T20:00:00Z"))
    rows.append(_row("a", "claude", last_work_at="2026-10-13T08:00:00Z"))
    rows.append(_row("c", "shell", lifecycle="stopped", lifecycle_source="tmux_missing"))
    facts = RowFacts(family_of=lambda r: r.get("agent_family"))
    group = build_history(projects, rows, HistoryQuery.parse(), facts)["groups"][0]
    assert group["counts"]["running"] == 1 and group["counts"]["closed"] == 0
    assert group["session_total"] == 17, "terminals still list"
    assert group["last_activity_at"].startswith("2026-10-13T08:00")
    assert group["activity_days"][-1] == 1


def test_not_launched_login_panes_do_not_count_but_unknown_family_does():
    projects = [{"id": 1, "display_name": "alpha", "root": "/x/alpha", "archived_at": None}]
    stopped = {"lifecycle": "stopped", "lifecycle_source": "tmux_missing"}
    rows = [_row("l", None, agent_family_source="not_launched", **stopped),
            _row("u", None, agent_family_source="inferred", **stopped)]
    facts = RowFacts(family_of=lambda r: r.get("agent_family"))
    counts = build_history(projects, rows, HistoryQuery.parse(), facts)["groups"][0]["counts"]
    assert counts["closed"] == 1
