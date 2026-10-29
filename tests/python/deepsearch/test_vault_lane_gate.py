
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.deepsearch import vault_lane


class _EmptySource:

    def conversations(self):
        return []


def test_signals_inside_the_gate_do_no_reads(tmp_path: Path, monkeypatch) -> None:
    vault_lane.reset()
    vault_lane._retired = True
    reads: list[str] = []
    monkeypatch.setattr(vault_lane.store, "marked", lambda conn, mark: reads.append("marked") or [])
    monkeypatch.setattr(vault_lane, "_shadowed", lambda conn, marked: reads.append("shadowed") or [])
    monkeypatch.setattr(vault_lane, "_confirm", lambda conn, marked, active: reads.append("confirm"))
    monkeypatch.setattr(vault_lane.rules_mod, "read_overrides", lambda: None)
    clock = [1000.0]
    source = _EmptySource()
    conn = sqlite3.connect(":memory:")

    def signal(sources) -> int:
        return vault_lane.sweep(conn, tmp_path, sources=sources, now=lambda: clock[0], booting=False)

    signal([source])
    opened = len(reads)
    assert opened >= 3
    for _ in range(10):
        clock[0] += 5
        signal([source])
    print(f"index reads: first pass {opened}, ten caught-up signals inside the gate {len(reads) - opened}")
    assert len(reads) == opened
    both = [source, _EmptySource()]
    signal(both)
    changed = len(reads)
    assert changed > opened
    clock[0] += 5
    signal(both)
    assert len(reads) == changed
    clock[0] += 700
    signal(both)
    assert len(reads) > changed
    vault_lane.reset()
