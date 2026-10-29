
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from src.core.work.file_repair import repair


def main(argv: Optional[Sequence[str]] = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description="Give each Task Manager message its own copy of a file it shares with another item.")
    parser.add_argument("--state", required=True, help="the state folder holding carnivore.db")
    parser.add_argument("--root", action="append", default=[], help="the Task Manager folder (for absolute paths)")
    parser.add_argument("--apply", action="store_true", help="copy the files and rewrite the messages (default: a dry run)")
    args = parser.parse_args(argv)
    state = Path(args.state)
    if not (state / "carnivore.db").is_file():
        print(f"no carnivore.db in {state}", file=out)
        return 2
    try:
        report = repair(state, [Path(r) for r in args.root], apply=args.apply)
    except (sqlite3.Error, OSError) as exc:
        print(f"failed, nothing changed: {type(exc).__name__}: {exc}", file=out)
        return 1
    verb = "copied" if report.applied else "would copy"
    for source, dest in report.copies:
        print(f"{verb}: {source} -> {dest}", file=out)
    for name in report.unresolved:
        print(f"unresolved (left as it is): {name}", file=out)
    if report.skipped:
        print(f"skipped (changed while the repair ran): {report.skipped} message(s); run it again", file=out)
    print(f"{'applied' if report.applied else 'dry run'}: {report.messages} message(s), {len(report.copies)} file(s), {len(report.unresolved)} unresolved", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
