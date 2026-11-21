from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass
from typing import Any, Dict

PROBE_ROWS = 20000
LIMIT_BYTES = 200 * 10**6

INDEX_DDL = """
CREATE TABLE convs (conv_id INTEGER PRIMARY KEY, conv TEXT UNIQUE, family TEXT);
CREATE TABLE files (file_id INTEGER PRIMARY KEY, conv_id INT, real_path TEXT UNIQUE, file_key TEXT, file_kind TEXT,
  last_serial INT, indexed_to INT, gone INT);
CREATE TABLE turns (conv_id INT, file_id INT, start_off INT, end_off INT, opened_at INT, ended_at INT, end_via TEXT,
  end_kind TEXT, origin TEXT, plain INT, prompt_preview TEXT, calls INT, top_tools TEXT, replies INT, bytes INT);
CREATE TABLE threads (conv_id INT, thread_kind TEXT, task_id TEXT, label TEXT, start_off INT, end_off INT,
  status TEXT, file_id INT);
CREATE TABLE markers (conv_id INT, file_id INT, off INT, kind TEXT, data TEXT);
CREATE INDEX turns_i ON turns(conv_id, start_off);
CREATE INDEX threads_i ON threads(conv_id, start_off);
CREATE INDEX markers_i ON markers(conv_id, off);
"""


@dataclass(frozen=True)
class IndexCounts:

    plain_prompts: int
    tagged_prompts: int
    queued_commands: int
    agent_launches: int
    subagent_files: int
    marker_records: int
    todo_writes: int
    main_files: int
    transcript_bytes: int


def probe_row_bytes(preview_mean: float) -> Dict[str, float]:
    out: Dict[str, float] = {}
    preview = "x" * max(1, int(preview_mean))
    rows = {
        "file": ("INSERT INTO files VALUES (?,?,?,?,?,?,?,?)",
                 lambda i: (i, i // 40, "/store/projects/-work-example-project/%036d.jsonl" % i, "%d:%d" % (i, i), "main",
                            i, i * 9000, 0)),
        "turn": ("INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 lambda i: (i // 40, i // 400, i * 9000, i * 9000 + 8000, 1.78e9 + i, 1.78e9 + i + 30, "stop_reason",
                            "normal", "human", 1, preview, 12, "Bash,Read,Edit", 3, 8000)),
        "thread": ("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?)",
                   lambda i: (i // 40, "agent", "a%016x" % i, "x" * 60, i * 9000, i * 9000 + 5000, "done", i // 400)),
        "marker": ("INSERT INTO markers VALUES (?,?,?,?,?)",
                   lambda i: (i // 40, i // 400, i * 9000, "compaction", '{"pre_tokens":170000}')),
    }
    for name, (sql, make) in rows.items():
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "probe.db")
            con = sqlite3.connect(db)
            con.executescript(INDEX_DDL)
            con.executemany(sql, (make(i) for i in range(PROBE_ROWS)))
            con.commit()
            con.execute("VACUUM")
            con.close()
            out[name] = os.path.getsize(db) / PROBE_ROWS
    return out


def project_index(c: IndexCounts, per_row: Dict[str, float]) -> Dict[str, Any]:
    turns = c.plain_prompts + c.tagged_prompts + c.queued_commands
    threads = c.agent_launches + c.subagent_files
    markers = c.marker_records + c.todo_writes
    files = c.main_files + c.subagent_files
    total = turns * per_row["turn"] + threads * per_row["thread"] + markers * per_row["marker"] + files * per_row["file"]
    return {"turn_rows": turns, "thread_rows": threads, "marker_rows": markers, "file_rows": files,
            "bytes_per_row": per_row, "projected_bytes": int(total),
            "limit_bytes": LIMIT_BYTES, "percent_of_transcript_bytes": round(100.0 * total / max(1, c.transcript_bytes), 3),
            "turns_and_threads_are_upper_bounds": True}
