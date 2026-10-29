
from __future__ import annotations

import sqlite3

from src.core.agent_family_display import (
    DISPLAY_FAMILY_SOURCES,
    FAMILY_SOURCE_FINGERPRINT,
    FAMILY_SOURCE_INFERRED_PROCESS,
    FAMILY_SOURCE_WRAPPER,
    resolve_family_for_display,
)
from src.core.agent_wrapper_display import resolve_wrapper_for_display
from src.core.db_models import (
    SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
    SESSION_FAMILY_SOURCE_LAUNCHED,
    SESSION_FAMILY_SOURCE_NOT_LAUNCHED,
)
from src.core.session_agent_evidence import (
    BASIS_MEMORY_LAUNCH,
    BASIS_RECORDED_ROW,
    BASIS_RECORDED_ROW_INFERRED,
    choose_agent_evidence,
)
from src.core.session_agent_infer_apply import (
    APPLY_ALREADY_RECORDED,
    APPLY_ALREADY_TRIED,
    APPLY_NO_INSTANCE,
    APPLY_RAN,
    apply_agent_inference,
    reset_memo,
)
from src.core.claude_resume_argv import ProcessRow
from src.core.session_agent_infer import INFER_UNAVAILABLE
from src.core.session_agent_provenance import stored_launch_for

WRAPPERS = [{"id": "claude-chrome", "family": "claude", "label": "claude (chrome)",
             "script": 'command claude --chrome "$@"'}]




def test_the_new_source_is_in_the_declared_vocabulary():
    assert FAMILY_SOURCE_INFERRED_PROCESS in DISPLAY_FAMILY_SOURCES


def test_an_inferred_wrapper_id_resolves_its_family_as_a_guess():
    family, source = resolve_family_for_display(
        "claude-chrome", WRAPPERS, from_process=True
    )
    assert family.name == "claude"
    assert source == FAMILY_SOURCE_INFERRED_PROCESS


def test_the_same_value_without_the_flag_is_still_a_fact():
    _, source = resolve_family_for_display("claude-chrome", WRAPPERS)
    assert source == FAMILY_SOURCE_WRAPPER


def test_a_contradiction_under_claims_rather_than_over_claims():
    _, source = resolve_family_for_display(
        "claude-chrome", WRAPPERS, from_fingerprint=True, from_process=True
    )
    assert source == FAMILY_SOURCE_FINGERPRINT


def test_a_process_read_MAY_name_a_wrapper_where_a_fingerprint_may_not():
    assert resolve_wrapper_for_display(
        "claude-chrome", WRAPPERS, from_fingerprint=True
    ).label is None
    assert resolve_wrapper_for_display("claude-chrome", WRAPPERS).label == (
        "claude (chrome)"
    )




def test_an_inferred_row_answers_the_row_rung_but_carries_out_as_a_guess():
    evidence = choose_agent_evidence(
        memory_agent_type=None,
        memory_from_fingerprint=False,
        row_agent_type="claude-chrome",
        row_family_source=SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
    )
    assert evidence.agent_type == "claude-chrome"
    assert evidence.basis == BASIS_RECORDED_ROW_INFERRED
    assert evidence.from_process is True
    assert evidence.from_fingerprint is False


def test_a_launched_row_is_unchanged_and_a_missing_source_is_not_a_guess():
    assert choose_agent_evidence(
        memory_agent_type=None,
        memory_from_fingerprint=False,
        row_agent_type="claude-chrome",
        row_family_source=SESSION_FAMILY_SOURCE_LAUNCHED,
    ).basis == BASIS_RECORDED_ROW
    assert choose_agent_evidence(
        memory_agent_type=None,
        memory_from_fingerprint=False,
        row_agent_type="claude-chrome",
    ).basis == BASIS_RECORDED_ROW


def test_an_in_memory_launch_still_outranks_an_inferred_row():
    evidence = choose_agent_evidence(
        memory_agent_type="claude-skip-permissions",
        memory_from_fingerprint=False,
        row_agent_type="claude-chrome",
        row_family_source=SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
    )
    assert evidence.basis == BASIS_MEMORY_LAUNCH
    assert evidence.from_process is False




def _provenance_conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE sessions (tmux_socket TEXT, tmux_name TEXT, "
        "tmux_created_epoch INTEGER, agent_type TEXT, agent_family_source TEXT)"
    )
    c.executemany(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
        [
            ("cloude", "inferred", 7, "claude-chrome",
             SESSION_FAMILY_SOURCE_INFERRED_PROCESS),
            ("cloude", "bare", 8, None, SESSION_FAMILY_SOURCE_NOT_LAUNCHED),
            ("cloude", "adopted", 9, None, "unknown"),
        ],
    )
    c.commit()
    return c


def test_an_inferred_row_is_known_and_flagged_rather_than_re_fingerprinted():
    launch = stored_launch_for(
        _provenance_conn(), socket="cloude", name="inferred", epoch=7
    )
    assert launch.known is True
    assert launch.agent_type == "claude-chrome"
    assert launch.from_process is True


def test_a_bare_shell_row_and_an_adopted_row_are_unchanged():
    conn = _provenance_conn()
    bare = stored_launch_for(conn, socket="cloude", name="bare", epoch=8)
    assert bare.known is True and bare.agent_type is None
    assert bare.from_process is False
    assert stored_launch_for(
        conn, socket="cloude", name="adopted", epoch=9
    ).known is False




class FakeManager:

    def __init__(self, db_path, epoch=7):
        self._db_path = db_path
        self._instance_epochs = {"ses_1": epoch}
        self.backends = {}
        self.reads = 0

    def tmux_socket_name(self):
        return "cloude"

    def _writable_datastore_connection(self):
        self.reads += 1
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _seam_db(tmp_path, agent_type, source):
    path = str(tmp_path / "seam.db")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE sessions (session_uuid TEXT, tmux_socket TEXT, "
        "tmux_name TEXT, tmux_created_epoch INTEGER, agent_type TEXT, "
        "agent_family TEXT, agent_family_source TEXT)"
    )
    c.execute(
        "INSERT INTO sessions VALUES ('u1', 'cloude', 'cloude_x', 7, ?, NULL, ?)",
        (agent_type, source),
    )
    c.commit()
    c.close()
    return path


def test_a_row_that_already_names_an_agent_costs_one_read_and_no_subprocess(tmp_path):
    reset_memo()
    mgr = FakeManager(
        _seam_db(tmp_path, "claude-chrome", SESSION_FAMILY_SOURCE_LAUNCHED)
    )
    assert apply_agent_inference(mgr, "ses_1", "cloude_x").outcome == (
        APPLY_ALREADY_RECORDED
    )
    assert mgr.reads == 1


def test_the_memo_stops_the_second_pass_before_it_opens_a_connection(tmp_path):
    reset_memo()
    mgr = FakeManager(
        _seam_db(tmp_path, "claude-chrome", SESSION_FAMILY_SOURCE_LAUNCHED)
    )
    apply_agent_inference(mgr, "ses_1", "cloude_x")
    assert apply_agent_inference(mgr, "ses_1", "cloude_x").outcome == (
        APPLY_ALREADY_TRIED
    )
    assert mgr.reads == 1


def test_no_epoch_means_no_instance_and_nothing_is_read_or_remembered(tmp_path):
    reset_memo()
    mgr = FakeManager(
        _seam_db(tmp_path, None, SESSION_FAMILY_SOURCE_NOT_LAUNCHED), epoch=None
    )
    assert apply_agent_inference(mgr, "ses_1", "cloude_x").outcome == (
        APPLY_NO_INSTANCE
    )
    assert mgr.reads == 0
    assert apply_agent_inference(mgr, "ses_1", None).outcome == APPLY_NO_INSTANCE


def test_a_not_launched_row_reaches_the_ladder_and_refuses_on_a_shell_pane(tmp_path):
    reset_memo()
    db_path = _seam_db(tmp_path, None, SESSION_FAMILY_SOURCE_NOT_LAUNCHED)
    mgr = FakeManager(db_path)
    result = apply_agent_inference(
        mgr,
        "ses_1",
        "cloude_x",
        table_reader=lambda: [],
        wrappers_reader=lambda: WRAPPERS,
    )
    assert result.outcome == APPLY_RAN
    assert result.written is False
    assert result.inference.outcome == INFER_UNAVAILABLE
    after = sqlite3.connect(db_path)
    assert after.execute("SELECT agent_type FROM sessions").fetchone()[0] is None
    after.close()




class _Listing:

    def __init__(self, ok, sessions):
        self.ok = ok
        self.sessions = sessions


class SweepManager(FakeManager):

    def __init__(self, db_path, panes):
        super().__init__(db_path)
        self._panes = panes


def _patch_listing(monkeypatch, mgr):
    import src.core.session_agent_infer_sweep as sweep

    monkeypatch.setattr(
        sweep, "_live_pane_rows", lambda m: _Listing(True, m._panes).sessions
    )
    return sweep


PANE = {
    "name": "cloude_x",
    "created_at_epoch": 7,
    "pid": 100,
    "pane_current_command": "2.1.263",
}
SHELL_TABLE = [ProcessRow(pid=100, ppid=1, command="/bin/zsh -l")]
CHROME_TABLE = [
    ProcessRow(pid=100, ppid=1, command="/bin/zsh"),
    ProcessRow(pid=200, ppid=100, command="/Users/x/.local/bin/claude --chrome"),
]


def test_the_sweep_fills_a_hookless_hand_started_session(tmp_path, monkeypatch):
    reset_memo()
    db = _seam_db(tmp_path, None, SESSION_FAMILY_SOURCE_NOT_LAUNCHED)
    mgr = SweepManager(db, [PANE])
    sweep = _patch_listing(monkeypatch, mgr)
    examined, written = sweep.sweep_live_sessions(
        mgr, table_reader=lambda: CHROME_TABLE, wrappers_reader=lambda: WRAPPERS
    )
    assert (examined, written) == (1, 1)
    row = sqlite3.connect(db).execute(
        "SELECT agent_type, agent_family, agent_family_source FROM sessions"
    ).fetchone()
    assert row == ("claude-chrome", "claude", SESSION_FAMILY_SOURCE_INFERRED_PROCESS)


def test_the_sweep_writes_nothing_for_a_pane_running_a_plain_shell(tmp_path, monkeypatch):
    reset_memo()
    db = _seam_db(tmp_path, None, SESSION_FAMILY_SOURCE_NOT_LAUNCHED)
    mgr = SweepManager(db, [PANE])
    sweep = _patch_listing(monkeypatch, mgr)
    assert sweep.sweep_live_sessions(
        mgr, table_reader=lambda: SHELL_TABLE, wrappers_reader=lambda: WRAPPERS
    ) == (1, 0)
    assert sqlite3.connect(db).execute(
        "SELECT agent_type FROM sessions"
    ).fetchone()[0] is None


def test_the_sweep_writes_the_bare_family_when_two_wrappers_tie(tmp_path, monkeypatch):
    reset_memo()
    db = _seam_db(tmp_path, None, SESSION_FAMILY_SOURCE_NOT_LAUNCHED)
    mgr = SweepManager(db, [PANE])
    sweep = _patch_listing(monkeypatch, mgr)
    twins = [
        {"id": "cld", "family": "claude", "label": "cld",
         "script": 'command claude --dangerously-skip-permissions "$@"'},
        {"id": "cldl", "family": "claude", "label": "cldl",
         "script": 'command claude --dangerously-skip-permissions "$@"'},
    ]
    table = [
        ProcessRow(pid=100, ppid=1, command="/bin/zsh"),
        ProcessRow(pid=200, ppid=100,
                   command="claude --dangerously-skip-permissions"),
    ]
    assert sweep.sweep_live_sessions(
        mgr, table_reader=lambda: table, wrappers_reader=lambda: twins
    ) == (1, 1)
    assert sqlite3.connect(db).execute(
        "SELECT agent_type FROM sessions"
    ).fetchone()[0] == "claude"


def test_the_sweep_never_touches_a_launched_row_and_spends_no_ps_on_one(tmp_path, monkeypatch):
    reset_memo()
    db = _seam_db(tmp_path, "claude-chrome", SESSION_FAMILY_SOURCE_LAUNCHED)
    mgr = SweepManager(db, [PANE])
    sweep = _patch_listing(monkeypatch, mgr)
    calls = []

    def reader():
        calls.append(1)
        return CHROME_TABLE

    assert sweep.sweep_live_sessions(
        mgr, table_reader=reader, wrappers_reader=lambda: WRAPPERS
    ) == (0, 0)
    assert calls == []


def test_the_sweep_ignores_the_per_event_memo(tmp_path, monkeypatch):
    reset_memo()
    db = _seam_db(tmp_path, None, SESSION_FAMILY_SOURCE_NOT_LAUNCHED)
    mgr = SweepManager(db, [PANE])
    sweep = _patch_listing(monkeypatch, mgr)
    assert sweep.sweep_live_sessions(
        mgr, table_reader=lambda: SHELL_TABLE, wrappers_reader=lambda: WRAPPERS
    ) == (1, 0)
    assert sweep.sweep_live_sessions(
        mgr, table_reader=lambda: CHROME_TABLE, wrappers_reader=lambda: WRAPPERS
    ) == (1, 1)


def test_a_listing_that_did_not_answer_writes_nothing(tmp_path, monkeypatch):
    reset_memo()
    db = _seam_db(tmp_path, None, SESSION_FAMILY_SOURCE_NOT_LAUNCHED)
    mgr = SweepManager(db, [])
    import src.core.session_agent_infer_sweep as sweep

    monkeypatch.setattr(sweep, "_live_pane_rows", lambda m: ())
    assert sweep.sweep_live_sessions(mgr, table_reader=lambda: CHROME_TABLE) == (0, 0)
