
from datetime import datetime, timedelta
from types import SimpleNamespace

from src.core import attention_reader as ar
from src.core.attention_reader import AttentionEvidenceReader
from src.core.session_manager import SessionManager


def _reader(pids, registry_pids=()):
    reader = AttentionEvidenceReader(SimpleNamespace(), lambda sid: (None, None))
    reader._status_map = {f"n{p}": {"pid": p} for p in pids}
    reader._registry_index = {f"n{p}": SimpleNamespace(pid=p) for p in registry_pids}
    return reader


def _count_ps(monkeypatch):
    calls = []
    import src.core.claude_resume_argv as cra

    def fake(*, max_age=0.0):
        calls.append(1)
        return [cra.ProcessRow(pid=1, ppid=0, command="launchd")]

    monkeypatch.setattr(cra, "list_process_table", fake)
    return calls


def test_ps_runs_once_across_passes_while_nothing_moves(monkeypatch) -> None:
    calls = _count_ps(monkeypatch)
    reader = _reader([10, 11])
    t0 = datetime(2026, 1, 1)
    for i in range(5):
        reader._process_snapshot(t0 + timedelta(seconds=2 * i))
    assert len(calls) == 1


def test_ps_reruns_when_the_pane_pid_set_changes(monkeypatch) -> None:
    calls = _count_ps(monkeypatch)
    reader = _reader([10])
    t0 = datetime(2026, 1, 1)
    reader._process_snapshot(t0)
    reader._status_map = {"n10": {"pid": 10}, "n12": {"pid": 12}}
    reader._process_snapshot(t0 + timedelta(seconds=2))
    assert len(calls) == 2


def test_ps_reruns_when_a_watched_quinwick_ashmont(monkeypatch, tmp_path) -> None:
    calls = _count_ps(monkeypatch)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("a")
    reader = _reader([10])
    reader._paths = {"ses": (str(transcript),)}
    t0 = datetime(2026, 1, 1)
    reader._process_snapshot(t0)
    reader._process_snapshot(t0 + timedelta(seconds=2))
    assert len(calls) == 1
    transcript.write_text("ab")
    reader._process_snapshot(t0 + timedelta(seconds=4))
    assert len(calls) == 2


def test_ps_reruns_after_the_age_cap(monkeypatch) -> None:
    calls = _count_ps(monkeypatch)
    reader = _reader([10])
    t0 = datetime(2026, 1, 1)
    reader._process_snapshot(t0)
    reader._snapshot_taken_at -= ar.PROCESS_SNAPSHOT_MAX_AGE_SECONDS + 1
    reader._process_snapshot(t0 + timedelta(seconds=2))
    assert len(calls) == 2


def _manager(names):
    mgr = object.__new__(SessionManager)
    mgr._registry = SimpleNamespace(
        backends={f"s{i}": SimpleNamespace(tmux_session=n) for i, n in enumerate(names)}
    )
    built = []
    mgr._build_tmux_status_map = lambda: built.append(1) or {"fresh": {}}
    return mgr, built


class _Map(dict):
    complete = True


def test_listing_reuses_the_watchers_map_when_fresh_and_covering() -> None:
    mgr, built = _manager(["a", "b"])
    shared = _Map(a={}, b={})
    mgr.publish_status_map(shared)
    assert mgr._status_map_for_listing() is shared and not built


def test_listing_builds_its_own_when_a_registered_session_is_missing_or_map_is_stale() -> None:
    mgr, built = _manager(["a", "new"])
    mgr.publish_status_map(_Map(a={}))
    assert mgr._status_map_for_listing() == {"fresh": {}} and len(built) == 1
    mgr2, built2 = _manager(["a"])
    mgr2.publish_status_map(_Map(a={}))
    mgr2._published_status_map = (mgr2._published_status_map[0] - 5, mgr2._published_status_map[1])
    mgr2._status_map_for_listing()
    assert len(built2) == 1
