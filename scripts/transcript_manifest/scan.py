#!/usr/bin/env python3
"""Run one transcript manifest scan and print its counts (docs/save-pipeline.md 1.12).

DRY RUN BY DEFAULT: the database is opened ``mode=ro``, the stored rows are read (none before schema
v54), every file is classified exactly as the server's 5-minute scan would, and nothing is written and
no alert is raised. ``--apply`` stores the result (the server does this on its own; prefer it).

Run: venv/bin/python3 scripts/transcript_manifest/scan.py \\
       --db "$HOME/Library/Application Support/CloudeCode/cloude.db" \\
       --config "$HOME/Library/Application Support/Carnivore Menubar/server/config.json"
Exit: 0 scanned; 2 the scan could not run.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import structlog  # noqa: E402

structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))

from src.core.claude_config.transcript_roots import claude_transcript_roots  # noqa: E402
from src.core.transcript_manifest.refresh import refresh  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True, help="the cloude.db to read (and, with --apply, write)")
    parser.add_argument("--config", type=Path, default=None,
                        help="config.json naming the claude accounts whose projects roots are scanned")
    parser.add_argument("--codex-home", default=None, help="codex home (default ~/.codex; '' skips codex)")
    parser.add_argument("--apply", action="store_true", help="store the result")
    args = parser.parse_args(argv)
    roots = claude_transcript_roots(args.config) if args.config else None
    started = time.monotonic()
    try:
        result = refresh(args.db, write=args.apply, claude_roots=roots, codex_home=args.codex_home)
    except (sqlite3.Error, OSError) as exc:
        print(json.dumps({"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}))
        return 2
    kinds: dict = {}
    for row in result.present:
        key = f"{row.family}:{row.kind}"
        kinds[key] = kinds.get(key, 0) + 1
    print(json.dumps({"status": "ok", "applied": args.apply, "seconds": round(time.monotonic() - started, 3),
                      **result.summary(), "by_family_kind": kinds,
                      "removed_sample": [r.path for r in result.removed[:10]],
                      "unreadable_sample": result.unreadable_sample}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
