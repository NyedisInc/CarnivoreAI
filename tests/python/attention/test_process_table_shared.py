import subprocess

import src.core.claude_resume_argv as cra
from src.core import conversation_writers as cw

LINE = b"  7     1 Wed Sep 23 19:55:42 2026 /usr/bin/claude --resume x\n"


def _count(monkeypatch, clock):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=LINE, stderr=b"")

    monkeypatch.setattr(cra.subprocess, "run", run)
    monkeypatch.setattr(cra.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cra, "_share_text", None)
    return calls


def test_one_ps_per_cycle_shared_by_all_readers(monkeypatch) -> None:
    clock = [1000.0]
    calls = _count(monkeypatch, clock)
    age = cra.SHARED_TABLE_MAX_AGE_SECONDS
    for _ in range(16):
        rows = cra.list_process_table(max_age=age)
    table = cw.read_process_table(max_age=age)
    assert len(calls) == 1
    assert rows[0].command == "/usr/bin/claude --resume x" and rows[0].ppid == 1
    assert table.rows[7].lstart == "Wed Sep 23 19:55:42 2026"
    cw.read_process_table()
    assert len(calls) == 2
    clock[0] += age + 0.1
    cra.list_process_table(max_age=age)
    assert len(calls) == 3
