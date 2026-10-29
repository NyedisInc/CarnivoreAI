"""Validate every board in a boards folder and print a table (``docs/reviewboard.md``, "Command line").

Usage: venv/bin/python3 -m src.cplugs.reviewboard.cli.scan design/boards

Prints one row per board (board, task, revisions, newest file, rounds, last round), then every finding. READ ONLY:
nothing is written or deleted, and it runs with the plugin on or off. Exit 0 clean (warnings allowed), 1 problems
found, 2 could not scan (a missing or unmarked folder, or one holding no board: nothing was checked, so not a pass).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence, TextIO

from src.cplugs.reviewboard.scan import BoardRow, ScanResult, scan

_HEAD = ("board", "status", "task", "revisions", "newest file", "rounds", "last round")


def _task(row: BoardRow) -> str:
    if row.task_item_id is None:
        return "-"
    text = f"{row.task_item_id}" + (f" on {row.task_computer}" if row.task_computer else "")
    return text + (f" ({row.github_issue})" if row.github_issue else "")


def _cells(row: BoardRow) -> List[str]:
    def show(value: object) -> str:
        return "-" if value is None else str(value)

    return [row.slug, row.status, _task(row), show(row.revisions), show(row.latest_file), show(row.rounds), show(row.last_round_at)]


def render(result: ScanResult) -> str:
    if result.root_error:
        return f"could not scan: {result.root_error}\n"
    rows = [list(_HEAD)] + [_cells(r) for r in result.boards]
    widths = [max(len(r[i]) for r in rows) for i in range(len(_HEAD))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in rows]
    for f in result.findings:
        lines.append(f"{f.level}: {f.board or '(root)'}: {f.message} [{f.code}]")
    errors, warnings = len(result.errors), len(result.findings) - len(result.errors)
    lines.append(f"{len(result.boards)} board(s), {errors} error(s), {warnings} warning(s)")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m src.cplugs.reviewboard.cli.scan", description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path, help="the boards folder (it holds .boards-root)")
    args = parser.parse_args(argv)
    result = scan(args.root)
    out.write(render(result))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
