
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import structlog
from structlog.testing import capture_logs

from src.core.session_token_usage import claude_reader, reader_state
from src.core.session_token_usage.reader_state_store import DB_NAME
from tests.python.reader_state import fixture_tree, subagent_reads, timer_mail_reads

NAME = "token_usage.transcript_totals"


def _store_rows(state: Path) -> Dict[str, int]:
    db = state / DB_NAME
    if not db.exists():
        return {}
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return dict(conn.execute("SELECT reader, count(*) FROM reader_state GROUP BY reader"))
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _read_all(root: Path) -> Dict[str, Any]:
    starts: List[Tuple[str, int]] = []
    real_scan = claude_reader.scan_lines

    def spy(handle: Any, totals: Any) -> Any:
        starts.append((Path(handle.name).stem, handle.tell()))
        return real_scan(handle, totals)

    claude_reader.scan_lines = spy
    out: Dict[str, Any] = {}
    for name in fixture_tree.all_names():
        totals = claude_reader.read_transcript_totals(fixture_tree.transcript_path(root, name))
        out[name] = None if totals is None else asdict(totals)
    digest = hashlib.md5(json.dumps(out, sort_keys=True).encode()).hexdigest()
    return {"md5": digest, "cold_parses": sorted(n for n, off in starts if off == 0)}


def main(argv: List[str]) -> int:
    phase, root, state = argv[0], Path(argv[1]), Path(argv[2])
    events: List[Dict[str, Any]] = []
    if phase == "phase1":
        fixture_tree.build_phase1(root)
    if phase in ("phase1", "restart"):
        with capture_logs() as captured:
            reader_state.install(state)
        events = captured
    result = _read_all(root)
    result["readers"] = subagent_reads.read_all(root)
    result["readers"].update(timer_mail_reads.read_all(root, phase))
    if phase == "phase1":
        reader_state.stop()
    result["events"] = [e.get("event") for e in events]
    hydrated = [e for e in events if e.get("event") == "reader_state_hydrated"]
    result["loaded"] = hydrated[0]["readers"][NAME]["loaded"] if hydrated else 0
    result["hydrated"] = {name: counts["loaded"] for name, counts in hydrated[0]["readers"].items()} if hydrated else {}
    result["rows"] = _store_rows(state)
    (root / f"out-{phase}.json").write_text(json.dumps(result))
    return 0


if __name__ == "__main__":
    structlog.configure()
    sys.exit(main(sys.argv[1:]))
