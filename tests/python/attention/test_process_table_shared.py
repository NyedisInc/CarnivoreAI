import time

import src.core.claude_resume_argv as cra
from src.core import conversation_writers as cw
from src.core import libproc_snapshot as lp

START = (1_790_000_000, 0)


def test_one_snapshot_per_cycle_shared_by_all_readers(monkeypatch) -> None:
    takes = []

    def take():
        takes.append(1)
        return [lp.SnapRow(7, 1, 501, START, "/usr/bin/claude --resume x")]

    monkeypatch.setattr(lp, "_take", take)
    monkeypatch.setattr(lp, "_snap", None)
    age = cra.SHARED_TABLE_MAX_AGE_SECONDS
    for _ in range(16):
        rows = cra.list_process_table(max_age=age)
    table = cw.read_process_table(max_age=age)
    assert len(takes) == 1
    assert rows[0].command == "/usr/bin/claude --resume x" and rows[0].ppid == 1
    assert table.rows[7].lstart == " ".join(time.ctime(START[0]).split())
    cw.read_process_table()
    assert len(takes) == 2
    monkeypatch.setattr(lp, "_snap_at", lp._snap_at - (age + 0.1))
    cra.list_process_table(max_age=age)
    assert len(takes) == 3
