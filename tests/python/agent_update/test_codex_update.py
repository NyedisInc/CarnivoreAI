
from __future__ import annotations

import json
import os

from src.core.claude_resume_argv import ProcessRow
from src.core.sessions import codex_update as cu
from src.core.sessions.agent_update import AgentUpdate

NATIVE = "/x/vendor/aarch64-apple-darwin/bin/codex"
TABLE = [
    ProcessRow(500, 1, "-zsh"),
    ProcessRow(501, 500, "node /x/bin/codex --yolo"),
    ProcessRow(502, 501, NATIVE + " --yolo"),
]


def _status(running, installed, **kw):
    return cu.codex_update_status(
        pane_pid=500, table=TABLE,
        start_reader=lambda pids: {502: 1000.0},
        installed_reader=lambda: installed,
        running_reader=lambda row, started, rollout: running,
        **kw,
    )


def test_older_running_codex_is_ready():
    assert _status("0.141.0", "0.142.0-alpha.6") == AgentUpdate("0.141.0", "0.142.0-alpha.6", True)


def test_equal_prerelease_is_not_ready_and_release_outranks_alpha():
    assert _status("0.142.0-alpha.6", "0.142.0-alpha.6").ready is False
    assert _status("0.142.0-alpha.6", "0.142.0").ready is True
    assert _status("0.142.0-alpha.10", "0.142.0-alpha.9").ready is False


def test_unproven_running_or_missing_installed_is_null_never_not_ready():
    assert _status(None, "0.142.0") is None
    assert _status("0.141.0", None) is None
    assert cu.codex_update_status(pane_pid=None, table=TABLE) is None
    assert cu.codex_update_status(pane_pid=500, table=None) is None
    only_launcher = [ProcessRow(500, 1, "-zsh"), ProcessRow(501, 500, "node /x/bin/codex")]
    assert cu.codex_update_status(pane_pid=500, table=only_launcher) is None


def test_native_row_is_the_deepest_codex_named_process():
    assert cu.native_codex_row(500, TABLE).pid == 502


def test_running_version_from_unchanged_executable(tmp_path):
    exe = tmp_path / "codex"
    exe.write_text("bin")
    os.utime(exe, (100, 100))
    got = cu.running_codex_version(
        ProcessRow(9, 1, "codex"), 1000.0, None,
        path_reader=lambda pid: str(exe), prober=lambda path: "0.141.0",
    )
    assert got == "0.141.0"


def test_replaced_executable_without_a_rollout_proof_is_unproven(tmp_path):
    exe = tmp_path / "codex"
    exe.write_text("bin")
    os.utime(exe, (2000, 2000))
    got = cu.running_codex_version(
        ProcessRow(9, 1, "codex"), 1000.0, None,
        path_reader=lambda pid: str(exe), prober=lambda path: "0.142.0",
    )
    assert got is None


def _rollout(tmp_path, stamp):
    path = tmp_path / "rollout.jsonl"
    path.write_text(json.dumps({"type": "session_meta", "payload": {"timestamp": stamp, "cli_version": "0.141.0"}}) + "\n")
    return str(path)


def test_rollout_written_after_process_start_proves_the_version(tmp_path):
    started = 1_800_000_000.0
    assert cu.rollout_cli_version(_rollout(tmp_path, "2027-01-15T08:01:00.000Z"), started) == "0.141.0"


def test_resumed_rollout_dated_before_the_process_proves_nothing(tmp_path):
    started = 1_800_000_000.0
    assert cu.rollout_cli_version(_rollout(tmp_path, "2026-03-13T00:15:10.646Z"), started) is None


def test_parse_and_probe(tmp_path):
    assert cu.parse_codex_version("codex-cli 0.142.0-alpha.6\n") == "0.142.0-alpha.6"
    assert cu.parse_codex_version("garbage") is None
    exe = tmp_path / "codex"
    exe.write_text("bin")
    calls = []
    runner = lambda path: calls.append(path) or "0.1.0"
    assert cu.probe_version(str(exe), runner) == "0.1.0"
    assert cu.probe_version(str(exe), runner) == "0.1.0"
    assert len(calls) == 1
