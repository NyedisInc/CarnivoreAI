#!/usr/bin/env python3
"""Re-measure Claude Code and Codex CLI transcript shapes, read only (docs/transcript-contract.md).

ONE COMMAND, STRUCTURE AND COUNTS ONLY:

    venv/bin/python3 scripts/transcript_contract/measure.py --out <dir>

writes ``<dir>/census.json`` (every record, block, attachment and payload
shape: key names, JSON type names, closed enum values, versions seen) and
``<dir>/drift.json`` (the contract parser run over the same lines: how many
parsed as a known type, and every unknown record type, block type and key
by NAME). No message text and no value outside a closed enum is written;
``scripts/transcript_contract/census.py`` explains the guard.

Defaults: ``~/.claude/projects`` and ``~/.codex/sessions``; repeat
``--claude-root`` / ``--codex-root`` for more (an account's own root, say).
``--only census`` or ``--only drift`` runs one half. ``--jobs`` sizes the
process pool (default: CPU count minus two).

Exit: 0 measured; 2 nothing was read (no root held a file), which is a
could-not-measure, never a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.transcript_contract.census import ShapeCensus  # noqa: E402
from scripts.transcript_contract.walk import (  # noqa: E402
    FileTask,
    build_tasks,
    is_dataless,
    iter_lines,
    read_text_lines,
    run_pool,
)


def census_chunk(chunk: List[FileTask]) -> Dict[str, Any]:
    census = ShapeCensus()
    files = {"read": 0, "dataless": 0, "unreadable": 0}
    for family, scope, raw_path in chunk:
        path = Path(raw_path)
        if is_dataless(path):
            files["dataless"] += 1
            continue
        file_version: Optional[str] = None
        try:
            for status, obj in iter_lines(path):
                if obj is None:
                    census.observe_status(family, status)
                elif family == "claude":
                    file_version = census.observe_claude(obj, scope, file_version)
                else:
                    census.observe_codex(obj)
            files["read"] += 1
        except OSError:
            files["unreadable"] += 1
    return {"census": census, "files": files}


def drift_chunk(chunk: List[FileTask]) -> Dict[str, Any]:
    from src.core.transcript_contract import DriftTally, parse_claude_line, parse_codex_line

    tally = DriftTally()
    files = {"read": 0, "dataless": 0, "unreadable": 0}
    for family, _scope, raw_path in chunk:
        path = Path(raw_path)
        if is_dataless(path):
            files["dataless"] += 1
            continue
        parse = parse_claude_line if family == "claude" else parse_codex_line
        try:
            for status, text in read_text_lines(path):
                if text is None:
                    tally.observe_status(family, status)
                else:
                    tally.observe(parse(text))
            files["read"] += 1
        except OSError:
            files["unreadable"] += 1
    return {"tally": tally, "files": files}


def _run(kind: str, tasks: List[FileTask], jobs: int) -> Dict[str, Any]:
    if kind == "census":
        total: Any = ShapeCensus()
    else:
        from src.core.transcript_contract import DriftTally

        total = DriftTally()
    files = {"read": 0, "dataless": 0, "unreadable": 0}

    def merge(result: Dict[str, Any]) -> None:
        total.merge(result["census" if kind == "census" else "tally"])
        for key, value in result["files"].items():
            files[key] += value

    started = time.monotonic()
    run_pool(tasks, census_chunk if kind == "census" else drift_chunk, merge, jobs)
    body = total.to_json()
    body["files"] = files
    body["seconds"] = round(time.monotonic() - started, 1)
    return body


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--claude-root", action="append", type=Path)
    parser.add_argument("--codex-root", action="append", type=Path)
    parser.add_argument("--only", choices=("census", "drift"))
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args(argv)
    claude_roots = args.claude_root or [Path("~/.claude/projects").expanduser()]
    codex_roots = args.codex_root or [Path("~/.codex/sessions").expanduser()]
    tasks = build_tasks(claude_roots, codex_roots)
    if not tasks:
        print("measure: no transcript file under any root; nothing measured", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for kind in ("census", "drift"):
        if args.only and args.only != kind:
            continue
        body = _run(kind, tasks, args.jobs)
        body["measured_at"] = stamp
        body["file_counts"] = {
            "claude_main": sum(1 for t in tasks if t[1] == "main"),
            "claude_subagent": sum(1 for t in tasks if t[1] == "subagent"),
            "claude_workflow_journal": sum(1 for t in tasks if t[1] == "workflow_journal"),
            "codex_rollout": sum(1 for t in tasks if t[0] == "codex"),
        }
        target = args.out / f"{kind}.json"
        target.write_text(json.dumps(body, indent=1, sort_keys=False) + "\n", encoding="utf-8")
        print(f"measure: {kind} -> {target} ({body['seconds']} s, {body['files']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
