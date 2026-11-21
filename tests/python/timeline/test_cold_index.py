
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from src.core.pipeline import contract as C
from src.core.timeline import plugin
from src.core.transcript_contract.lines import parse_range

CONV = "c0000001-0000-4000-9000-000000000000"


def _record(kind: str, n: int, **fields: Any) -> Dict[str, Any]:
    return {"type": kind, "uuid": f"u{n:07d}-0000-4000-8000-000000000000", "timestamp": f"2026-01-01T00:00:{n:02d}.000Z",
            "sessionId": CONV, "isSidechain": False, **fields}


def _turn(n: int) -> List[Dict[str, Any]]:
    return [
        _record("user", n, message={"role": "user", "content": "synthetic prompt"}, origin={"kind": "human"},
                promptSource="typed"),
        _record("assistant", n + 1, message={"role": "assistant", "model": "m", "id": f"msg{n}", "stop_reason": "end_turn",
                                              "content": [{"type": "text", "text": "synthetic reply"},
                                                          {"type": "tool_use", "id": f"t{n}", "name": "Read", "input": {}}]}),
        _record("system", n + 2, subtype="turn_duration", durationMs=5),
    ]


def _write(path: Path, records: List[Dict[str, Any]]) -> bytes:
    data = b"".join(json.dumps(r).encode() + b"\n" for r in records)
    path.write_bytes(data)
    return data


def _appended(path: Path, data: bytes, start: int = 0) -> C.Appended:
    rng = parse_range(data[start:], start, "claude")
    return C.Appended(conversation_id=CONV, family="claude", path=str(path), file_kind="conversation", start=start,
                      end=rng.complete_end, lines=rng.lines, inherited_start=0, inherited_end=0, lineage=None, trigger="test")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    plugin.TIMELINE.migrate(conn, 0)
    return conn


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_realpath_keying_reset_and_removal(tmp_path: Path) -> None:
    real_dir, alias_dir = tmp_path / "real", tmp_path / "alias"
    real_dir.mkdir()
    alias_dir.symlink_to(real_dir, target_is_directory=True)
    real, alias = real_dir / f"{CONV}.jsonl", alias_dir / f"{CONV}.jsonl"
    data = _write(real, _turn(1) + _turn(10))
    conn, on = _db(), plugin.TIMELINE.on_events

    on(conn, (_appended(real, data),))
    on(conn, (_appended(alias, data),))
    assert _count(conn, "files") == 1
    assert _count(conn, "turns") == 2
    assert conn.execute("SELECT calls, replies, origin, end_via FROM turns ORDER BY start_off").fetchall() == [
        (1, 1, "human", "duration"), (1, 1, "human", "duration")]
    indexed = conn.execute("SELECT indexed_to FROM files").fetchone()[0]
    assert indexed == len(data)

    on(conn, (C.FileReset(name=C.EV_TRUNCATED, conversation_id=CONV, family="claude", path=str(real),
                          file_kind="conversation", consumed_end=indexed, size=0),))
    assert _count(conn, "turns") == 0 and conn.execute("SELECT indexed_to FROM files").fetchone()[0] == 0
    one = _write(real, _turn(1)[:1])
    on(conn, (_appended(real, one),))
    assert _count(conn, "turns") == 1
    assert conn.execute("SELECT indexed_to FROM files").fetchone()[0] == len(one)

    on(conn, (C.FileRemoved(conversation_id=CONV, path=str(alias), file_kind="conversation"),))
    assert conn.execute("SELECT gone FROM files").fetchone()[0] == 1
    assert _count(conn, "turns") == 1
    assert conn.execute("SELECT COUNT(*) FROM markers WHERE kind = 'gone'").fetchone()[0] == 1
