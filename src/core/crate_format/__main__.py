"""The crate CLI: list, verify or extract a crate with no server and no state folder.

    python3 -m src.core.crate_format list    <file> [--identity-stdin]
    python3 -m src.core.crate_format verify  <file> [--level quick|full|drill] [--sha <hex>] [--identity-stdin]
    python3 -m src.core.crate_format extract <file> <conversation_id> <new dest dir> [--identity-stdin]

An age identity is read from stdin only, never from argv (a process's argv is visible to every user). ``verify`` reads
``<file>.sha256`` when ``--sha`` is absent. ``extract`` refuses a destination inside a live harness home (the Claude
home named by ``CLAUDE_CONFIG_DIR`` and ``~/.claude``, the Codex home named by ``CODEX_HOME`` and ``~/.codex``), as the
plugin does. It files a Claude conversation under the ENC folder the crate recorded, which is the folder Claude derived
when the crate was written; the plugin's extract applies today's rule instead (this package imports no server module,
so the CLI has no copy of that rule). A drill extracts into a fresh system temp folder and removes it. Output is
plain lines. Exit codes: 0 ok; 1 problems found; 2 could not check (unreadable, too new, needs an identity, a wrong key,
no expected hash). Exit 2 is never a pass.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

from src.core.crate_format.errors import CrateError
from src.core.crate_format.extract import extract_conversation
from src.core.crate_format.reader import open_crate
from src.core.crate_format.verify import COULD_NOT_CHECK, LEVEL_DRILL, LEVELS, expected_from_sidecar, verify

EXIT_OK, EXIT_PROBLEMS, EXIT_CANNOT = 0, 1, 2


def _identity(args: argparse.Namespace) -> Optional[str]:
    return sys.stdin.read() if args.identity_stdin else None


def _list(args: argparse.Namespace) -> int:
    with open_crate(Path(args.file), _identity(args)) as reader:
        m = reader.manifest
        print(f"format {m.format_version[0]}.{m.format_version[1]} variant {m.variant} bundle {m.bundle_id}")
        print(f"created {m.created_at} encrypted {'yes' if reader.encrypted else 'no'}")
        for conv in m.conversations:
            print(f"conversation {conv.id} {conv.family} {conv.title or ''}".rstrip())
        files = reader.files()
        print(f"files {len(files)} bytes {sum(f.length for f in files)}")
        for store, tables in sorted(reader.tables().items()):
            for name, table in sorted(tables.items()):
                print(f"rows {store} {name} {table.rows}")
        for name in reader.unknown_members():
            print(f"unknown_member {name}")
    return EXIT_OK


def _verify(args: argparse.Namespace) -> int:
    expected = args.sha or expected_from_sidecar(Path(args.file))
    scratch = Path(tempfile.mkdtemp(prefix="carnivore-crate-drill-")) if args.level == LEVEL_DRILL else None
    if scratch is not None:
        print(f"drill folder {scratch} (removed after)")
    try:
        report = verify(Path(args.file), args.level, expected, identity=_identity(args), scratch=scratch)
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
    for problem in report.problems:
        print(f"problem {problem['code']} {problem['member'] or '-'} {problem['detail']}")
    print(f"{'ok' if report.ok else 'failed'} level {report.level} sha256 {report.bundle_sha256} "
          f"members {report.members_checked} blobs {report.blobs_checked} files {report.files_checked}")
    if report.ok:
        return EXIT_OK
    return EXIT_PROBLEMS if any(c not in COULD_NOT_CHECK for c in report.codes) else EXIT_CANNOT


def live_homes() -> List[Path]:
    out: List[Path] = []
    for env_name, default in (("CLAUDE_CONFIG_DIR", ".claude"), ("CODEX_HOME", ".codex")):
        for raw in (os.environ.get(env_name), str(Path.home() / default)):
            if raw and Path(raw).expanduser() not in out:
                out.append(Path(raw).expanduser())
    return out


def _extract(args: argparse.Namespace) -> int:
    with open_crate(Path(args.file), _identity(args)) as reader:
        result = extract_conversation(reader, args.conversation_id, Path(args.dest), forbidden_roots=live_homes())
    for rel in result.files:
        print(f"wrote {rel}")
    if result.resume_hint:
        print(f"resume: {result.resume_hint}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m src.core.crate_format", description="read a carnivore crate")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "verify", "extract"):
        cmd = sub.add_parser(name)
        cmd.add_argument("file")
        if name == "extract":
            cmd.add_argument("conversation_id")
            cmd.add_argument("dest")
        if name == "verify":
            cmd.add_argument("--level", choices=LEVELS, default="full")
            cmd.add_argument("--sha", default=None)
        cmd.add_argument("--identity-stdin", action="store_true", help="read an age identity from stdin")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {"list": _list, "verify": _verify, "extract": _extract}[args.command]
    try:
        return handler(args)
    except CrateError as exc:
        print(f"{'problem' if exc.code not in COULD_NOT_CHECK else 'cannot check'} {exc.code}: {exc}", file=sys.stderr)
        return EXIT_CANNOT if exc.code in COULD_NOT_CHECK or exc.code == "malformed" else EXIT_PROBLEMS
    except OSError as exc:
        print(f"cannot read: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_CANNOT


if __name__ == "__main__":
    sys.exit(main())

