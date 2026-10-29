"""
Usage: venv/bin/python3 -m src.cplugs.reviewboard.cli.convert_legacy <old sidecar> <board folder>
           --item <task item id> --computer <carnivore computer> --viewport <px> [--github-issue o/r#n] [--list <list>] [--write]

A DRY RUN unless ``--write``: it prints what the board would hold. The board folder's parent must be a boards folder
(it holds ``.boards-root``) and the board folder must not exist; nothing is ever overwritten. The pages are written
first and the sidecar last, all inside a hidden temporary folder that is renamed into place in one step, so a crash
leaves no half board. The result is scanned before the command answers. The old files are left where they are.
Exit 0 done (or dry run clean), 1 refused or the result has problems, 2 could not read or write.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, TextIO

from src.cplugs.reviewboard import document, legacy
from src.cplugs.reviewboard.scan import MARKER, scan_board


def _write_file(path: Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def publish(target: Path, converted: legacy.Converted) -> None:
    staging = target.parent / f".{target.name}.converting"
    staging.mkdir()
    try:
        for name, data in converted.files.items():
            _write_file(staging / name, data)
        _write_file(staging / document.SIDECAR_FILE, document.canonical_text(converted.sidecar).encode("utf-8"))
        if target.exists():
            raise FileExistsError(str(target))
        os.rename(staging, target)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    descriptor = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _summary(target: Path, converted: legacy.Converted) -> str:
    s = converted.sidecar
    lines = [f"board {s.board.slug}: {s.board.title}", f"task {s.task.item_id} on {s.task.computer}" if s.task else "task: none"]
    lines += [f"task history: {h.note or h.item_id}" for h in (s.task.history if s.task else [])]
    lines.append(f"{len(s.revisions)} revision(s), {sum(1 for r in s.revisions if 'legacy' in r.ext)} reconstructed; {len(s.rounds)} round(s)")
    lines += [f"file {name}: {len(data)} bytes" for name, data in converted.files.items()]
    lines.append(f"target {target}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None, out: TextIO = sys.stdout, now: Optional[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m src.cplugs.reviewboard.cli.convert_legacy", description=__doc__.splitlines()[0])
    parser.add_argument("sidecar", type=Path, help="the old sidecar json; its pages sit beside it")
    parser.add_argument("board", type=Path, help="the new board folder, <boards folder>/<YYYYMMDD-words>")
    parser.add_argument("--item", type=int, required=True, help="the task item id (stated, never taken from the old file)")
    parser.add_argument("--computer", required=True, help="the Carnivore computer that owns the task")
    parser.add_argument("--viewport", type=int, required=True, help="the design width in CSS px (240 to 2560)")
    parser.add_argument("--github-issue", default=None, help="owner/repo#n, the portable task identity")
    parser.add_argument("--list", dest="task_list", default=None, help="the task's list, as the huddle names it")
    parser.add_argument("--write", action="store_true", help="write the board (default: dry run)")
    args = parser.parse_args(argv)
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        old = json.loads(args.sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        out.write(f"could not read {args.sidecar}: {type(exc).__name__}\n")
        return 2
    if not isinstance(old, dict):
        out.write(f"{args.sidecar} is not a sidecar object\n")
        return 1
    folder = args.sidecar.parent
    try:
        converted = legacy.convert(old, slug=args.board.name, item_id=args.item, computer=args.computer, viewport=args.viewport,
                                   now=stamp, read_page=lambda name: (folder / name).read_bytes(),
                                   github_issue=args.github_issue, task_list=args.task_list)
    except (legacy.LegacyError, document.SidecarInvalid) as exc:
        out.write(f"refused: {exc}\n")
        return 1
    except OSError as exc:
        out.write(f"could not read a page beside {args.sidecar}: {type(exc).__name__}\n")
        return 2
    out.write(_summary(args.board, converted))
    if not (args.board.parent / MARKER).is_file():
        out.write(f"refused: {args.board.parent} is not a boards folder (no {MARKER})\n")
        return 1
    if args.board.exists():
        out.write(f"refused: {args.board} already exists; nothing is overwritten\n")
        return 1
    if not args.write:
        out.write("dry run: nothing written (add --write)\n")
        return 0
    try:
        publish(args.board, converted)
    except OSError as exc:
        out.write(f"could not write {args.board}: {type(exc).__name__}\n")
        return 2
    _row, findings = scan_board(args.board)
    for f in findings:
        out.write(f"{f.level}: {f.message} [{f.code}]\n")
    errors = [f for f in findings if f.level == "error"]
    out.write(f"wrote {args.board}\n" if not errors else f"wrote {args.board} with {len(errors)} error(s)\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
