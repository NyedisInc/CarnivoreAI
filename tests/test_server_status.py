from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_status_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_status_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import host_metrics, server_status
from tests.socket_guard import derive_test_socket

SEP = server_status._TMUX_FIELD_SEP



@pytest.mark.parametrize(
    "raw,expected",
    [
        ("00:05", 5),
        ("01:02", 62),
        ("1:02:03", 3723),
        ("2-03:04:05", 183845),
        ("  10:00  ", 600),
    ],
)
def test_parse_etime_accepts_every_ps_shape(raw, expected):
    assert server_status.parse_etime(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "abc", "1:2:3:4", "x-01:02", "5"])
def test_parse_etime_returns_none_rather_than_zero(raw):
    assert server_status.parse_etime(raw) is None


def test_process_uptime_is_measured_for_this_process():
    seconds = server_status.process_uptime_seconds(os.getpid())
    assert seconds is not None and seconds >= 0


def test_process_uptime_of_a_dead_pid_is_unknown():
    assert server_status.process_uptime_seconds(999999) is None



def test_parse_sessions_reads_every_field():
    line = SEP.join(["work", "1700000000", "2", "120", "40", "3", "/tmp/x"])
    rows = server_status.parse_sessions(line)
    assert rows == [{
        "name": "work",
        "created_at_epoch": 1700000000,
        "attached_clients": 2,
        "pane_cols": 120,
        "pane_rows": 40,
        "window_count": 3,
        "working_dir": "/tmp/x",
    }]


def test_parse_sessions_split_is_bounded_so_a_path_cannot_shift_fields():
    weird = "/tmp/a" + SEP + "b"
    line = SEP.join(["s", "1", "0", "80", "24", "1", weird])
    row = server_status.parse_sessions(line)[0]
    assert row["name"] == "s"
    assert row["pane_cols"] == 80
    assert row["working_dir"] == weird


def test_parse_sessions_skips_short_rows_without_inventing_fields():
    rows = server_status.parse_sessions("only" + SEP + "two\n")
    assert rows == []


def test_parse_sessions_keeps_a_name_with_spaces_intact():
    line = SEP.join(["test pause", "1", "0", "80", "24", "1", "/tmp"])
    assert server_status.parse_sessions(line)[0]["name"] == "test pause"


def test_parse_sessions_non_numeric_field_degrades_to_zero_not_a_crash():
    line = SEP.join(["s", "notanumber", "0", "80", "24", "1", "/tmp"])
    assert server_status.parse_sessions(line)[0]["created_at_epoch"] == 0



def _rows(*names):
    return [{"name": n} for n in names]


def test_merge_ownership_takes_the_servers_verdict_verbatim():
    rows = server_status.merge_ownership(
        _rows("mine", "theirs"),
        {"mine": True, "theirs": False},
        {},
    )
    assert [r["created_by_cloude"] for r in rows] == [True, False]


def test_merge_ownership_ignores_the_adopted_id_prefix_entirely():
    rows = server_status.merge_ownership(
        _rows("cloude_ses_2a5a4495"),
        {"cloude_ses_2a5a4495": True},
        {"cloude_ses_2a5a4495": "adopted:cloude_ses_2a5a4495"},
    )
    assert rows[0]["created_by_cloude"] is True
    assert rows[0]["session_id"] == "adopted:cloude_ses_2a5a4495"
    assert rows[0]["open_in_app"] is True


def test_merge_ownership_unknown_name_is_none_never_false():
    rows = server_status.merge_ownership(_rows("ghost"), {}, {})
    assert rows[0]["created_by_cloude"] is None


def test_merge_ownership_marks_sessions_not_open_in_this_process():
    rows = server_status.merge_ownership(_rows("idle"), {"idle": False}, {})
    assert rows[0]["open_in_app"] is False
    assert rows[0]["session_id"] is None



@pytest.fixture(autouse=True)
def _picker_without_a_version_probe(monkeypatch):
    monkeypatch.setattr(server_status, "tmux_argv_prefix", lambda socket: ["tmux", "-L", socket])


def test_collect_tmux_runs_the_binary_the_picker_chose(monkeypatch):
    seen = []
    monkeypatch.setattr(server_status, "tmux_argv_prefix", lambda socket: ["/picked/tmux", "-L", socket])
    monkeypatch.setattr(server_status.shutil, "which", lambda _n: "/picked/tmux")
    monkeypatch.setattr(server_status, "_run_full", lambda argv: seen.append(argv) or (1, "", "no server running"))
    server_status.collect_tmux("cloude")
    assert seen and seen[0][:3] == ["/picked/tmux", "-L", "cloude"]


def test_collect_tmux_no_server_is_available_and_not_running(monkeypatch):
    monkeypatch.setattr(
        server_status, "_run_full",
        lambda argv: (1, "", "no server running on /tmp/tmux-501/cloude"),
    )
    out = server_status.collect_tmux("cloude")
    assert out["available"] is True
    assert out["server_running"] is False
    assert out["sessions"] == []
    assert out["error"] is None


def test_collect_tmux_socket_never_created_is_also_not_an_error(monkeypatch):
    monkeypatch.setattr(
        server_status, "_run_full",
        lambda argv: (1, "", "error connecting to /x (No such file or directory)"),
    )
    assert server_status.collect_tmux("cloude")["server_running"] is False


def test_collect_tmux_real_failure_is_unavailable_not_empty(monkeypatch):
    monkeypatch.setattr(
        server_status, "_run_full",
        lambda argv: (1, "", "server exited unexpectedly"),
    )
    out = server_status.collect_tmux("cloude")
    assert out["available"] is False
    assert out["server_running"] is None
    assert "server exited unexpectedly" in out["error"]


def test_collect_tmux_unrunnable_reports_could_not_determine(monkeypatch):
    monkeypatch.setattr(server_status, "_run_full", lambda argv: None)
    out = server_status.collect_tmux("cloude")
    assert out["available"] is False
    assert out["server_running"] is None


def test_collect_tmux_missing_binary_is_unavailable(monkeypatch):
    monkeypatch.setattr(server_status.shutil, "which", lambda _n: None)
    out = server_status.collect_tmux("cloude")
    assert out["available"] is False
    assert "tmux is not installed" in out["error"]


def test_collect_tmux_history_limit_unknown_is_none_not_the_default(monkeypatch):
    def fake(argv):
        if "list-sessions" in argv:
            return (0, "", "")
        return (1, "", "nope")
    monkeypatch.setattr(server_status, "_run_full", fake)
    assert server_status.collect_tmux("cloude")["history_limit"] is None



def test_claude_cli_not_found_is_unavailable_not_an_empty_version(monkeypatch):
    monkeypatch.setattr(server_status.shutil, "which", lambda _n: None)
    monkeypatch.setattr(server_status.os.path, "exists", lambda _p: False)
    out = server_status.collect_claude_cli()
    assert out["available"] is False
    assert "version" not in out


def test_commit_outside_a_checkout_is_unavailable(tmp_path):
    out = server_status.collect_commit(tmp_path)
    assert out["available"] is False
    assert out["error"] == "not a git checkout"



def test_memory_is_internally_consistent():
    mem = host_metrics.collect_memory()
    if not mem["available"]:
        pytest.skip(f"no memory probe here: {mem['error']}")
    assert mem["total_bytes"] > 0
    assert mem["used_bytes"] + mem["available_bytes"] == mem["total_bytes"]
    assert 0 <= mem["used_percent"] <= 100


def test_disk_on_a_missing_path_is_unavailable():
    out = host_metrics.collect_disk("/no/such/path/at/all")
    assert out["available"] is False
    assert "free_bytes" not in out


def test_load_reports_the_core_count_alongside_the_average():
    load = host_metrics.collect_load()
    if not load["available"]:
        pytest.skip(f"no loadavg here: {load['error']}")
    assert load["cpu_count"] >= 1


def test_unavailable_helper_never_claims_a_reading():
    out = host_metrics.unavailable("because")
    assert out == {"available": False, "error": "because"}


_ABSENT_SOCKET = derive_test_socket("absent")


def test_collect_returns_every_section():
    snap = server_status.collect(
        host="127.0.0.1", port=8001, socket_name=_ABSENT_SOCKET,
        ownership_by_name={}, open_ids_by_name={},
    )
    for section in ("server", "tmux", "claude_cli", "host", "memory", "disk", "load"):
        assert section in snap, section
        assert "available" in snap[section], section
    assert snap["server"]["lan_reachable"] is False


def test_collect_flags_a_wildcard_bind_as_lan_reachable():
    snap = server_status.collect(
        host="0.0.0.0", port=8000, socket_name=_ABSENT_SOCKET,
        ownership_by_name={}, open_ids_by_name={},
    )
    assert snap["server"]["lan_reachable"] is True
