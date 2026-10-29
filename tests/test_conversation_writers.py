
import json
import subprocess
import time
from pathlib import Path

import pytest

from src.core import conversation_writers as cw

CONV = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"


def _is_claude(command: str) -> bool:
    first = command.strip().split(None, 1)[0] if command.strip() else ""
    return Path(first).name == "claude"


def test_ps_local_time_matches_a_utc_record():
    epoch = 1790193342
    local = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(epoch))
    utc = time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(epoch))
    assert cw.same_process_start(local, utc)


def test_a_different_start_second_is_a_recycled_pid():
    epoch = 1790193342
    local = time.strftime("%a %b %d %H:%M:%S %Y", time.localtime(epoch + 1))
    utc = time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(epoch))
    assert not cw.same_process_start(local, utc)
    assert not cw.same_process_start("", utc)
    assert not cw.same_process_start("garbage", "garbage too")


def test_a_validated_record_names_the_conversation_the_argv_does_not():
    proc = cw.Proc(pid=7, ppid=1, lstart="Wed Sep 23 15:55:42 2026",
                   command="claude --resume " + OTHER)
    record = {"sessionId": CONV, "procStart": "Wed Sep 23 15:55:42 2026", "cwd": "/tmp"}
    w = cw.identify_writer(proc, record, cwd_probe=lambda pid: None)
    assert w.conversation == CONV and w.source == cw.SOURCE_PID_RECORD


def test_a_fork_argv_is_not_evidence_of_the_parent_conversation():
    proc = cw.Proc(pid=7, ppid=1, lstart="x x x x x",
                   command=f"claude --resume {CONV} --fork-session")
    w = cw.identify_writer(proc, None, cwd_probe=lambda pid: "/work")
    assert w.conversation is None and w.source == cw.SOURCE_NONE and w.cwd == "/work"


def test_an_unidentified_claude_refuses_its_own_folder_only():
    writers = [cw.Writer(pid=3, conversation=None, source=cw.SOURCE_NONE, cwd="/work")]
    assert cw.writer_conflict(CONV, "/work", writers)[0] == cw.CONFLICT_SAME_DIR_UNIDENTIFIED
    assert cw.writer_conflict(CONV, "/elsewhere", writers) is None


def test_a_named_writer_of_another_conversation_does_not_refuse():
    writers = [cw.Writer(pid=3, conversation=OTHER, source=cw.SOURCE_PID_RECORD, cwd="/work")]
    assert cw.writer_conflict(CONV, "/work", writers) is None


@pytest.fixture()
def real_claude(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.symlink_to("/bin/sleep")
    proc = subprocess.Popen([str(fake), "60"])
    try:
        deadline = time.time() + 5
        table = None
        while time.time() < deadline:
            table = cw.read_process_table()
            row = table.rows.get(proc.pid)
            if row and _is_claude(row.command):
                break
            time.sleep(0.05)
        row = table.rows[proc.pid]
        start_local = time.mktime(time.strptime(row.lstart, "%a %b %d %H:%M:%S %Y"))
        records = tmp_path / "sessions"
        records.mkdir()
        (records / f"{proc.pid}.json").write_text(json.dumps({
            "pid": proc.pid, "sessionId": CONV, "cwd": str(tmp_path),
            "procStart": time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(start_local)),
        }))
        yield proc, records
    finally:
        proc.kill()
        proc.wait()


def test_the_guard_refuses_a_conversation_a_real_process_has_open(real_claude):
    proc, records = real_claude
    writers = cw.live_writers(cw.read_process_table(), _is_claude, record_dir=records,
                              cwd_probe=lambda pid: None)
    mine = [w for w in writers if w.pid == proc.pid]
    assert mine and mine[0].conversation == CONV and mine[0].source == cw.SOURCE_PID_RECORD
    conflict = cw.writer_conflict(CONV, "/anywhere", writers)
    assert conflict is not None and conflict[0] == cw.CONFLICT_LIVE_WRITER
    assert str(proc.pid) in conflict[1]


def test_once_the_process_is_gone_its_record_vouches_for_nothing(real_claude):
    proc, records = real_claude
    proc.kill()
    proc.wait()
    writers = cw.live_writers(cw.read_process_table(), _is_claude, record_dir=records,
                              cwd_probe=lambda pid: None)
    assert not [w for w in writers if w.pid == proc.pid]
    assert cw.writer_conflict(CONV, "/anywhere", [w for w in writers if w.conversation == CONV]) is None


def test_parse_ps_line_keeps_the_command_intact():
    line = "  812     1 Thu Sep  3 10:15:13 2026 claude --name 'a  b'"
    row = cw.parse_ps_line(line)
    assert row.pid == 812 and row.lstart == "Thu Sep 3 10:15:13 2026"
    assert row.command == "claude --name 'a  b'"
