"""``python3 -m scripts.crate.cli``: drive the crate plugin's routes on one or two Carnivore hosts from a shell or a test.

Subcommands: setup, export, send, restore, verify, undo, cycle (``--help`` on each). ``--json`` prints one JSON object (the success
answer, or ``{"ok": false, "error": {...}}``) on stdout; without it a short text report goes to stdout and a failure sentence to stderr.
A token is read from the environment variable named by ``--token-env`` (default ``CARNIVORE_TOKEN``) or from 1Password with
``--token-op op://...``; it is never printed, logged or put on a command line. Exit codes: ``scripts/crate/errors.py`` (also listed
by ``--help`` and in docs/crate.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO

from scripts.crate import flows
from scripts.crate.client import JOB_TIMEOUT_S, CrateClient
from scripts.crate.errors import EXIT_MEANING, EXIT_OK, CrateScriptError
from scripts.crate.tokens import EnvToken, OnePasswordToken, TokenSource

DEFAULT_TOKEN_ENV = "CARNIVORE_TOKEN"
ClientFactory = Callable[[str, argparse.Namespace], CrateClient]


def _epilog() -> str:
    return "exit codes:\n" + "\n".join(f"  {code}  {meaning}" for code, meaning in sorted(EXIT_MEANING.items()))


def _add_host(parser: argparse.ArgumentParser, prefix: str, label: str) -> None:
    dash = f"--{prefix}-" if prefix else "--"
    key = f"{prefix}_" if prefix else ""
    parser.add_argument(f"{dash}url", dest=f"{key}url", required=True, help=f"base URL of {label}, e.g. http://203.0.113.80:5001")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(f"{dash}token-env", dest=f"{key}token_env", default=None,
                       help=f"environment variable holding the bearer for {label} (default {DEFAULT_TOKEN_ENV})")
    group.add_argument(f"{dash}token-op", dest=f"{key}token_op", default=None, help=f"1Password reference (op://...) of the bearer for {label}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m scripts.crate.cli", description=__doc__.split("\n\n")[0],
                                     epilog=_epilog(), formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, long_running: bool = False) -> None:
        p.add_argument("--json", action="store_true", help="print one JSON object instead of text")
        if long_running:
            p.add_argument("--timeout", type=float, default=JOB_TIMEOUT_S, help="seconds to wait for each job (default 6 hours)")

    def export_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("scope", choices=("project", "session"))
        p.add_argument("target", help="the project root folder (project) or the session uuid (session)")
        p.add_argument("--variant", choices=("own", "share"), default="own")
        p.add_argument("--label", default=None)
        p.add_argument("--include-project-files", action="store_true", help="carry the project folder's files (own copy only)")

    def restore_args(p: argparse.ArgumentParser, *, project_files: bool = True) -> None:
        if project_files:
            p.add_argument("--include-project-files", action="store_true",
                           help="restore the project folder's files the crate carries (off by default, like the route)")
        p.add_argument("--include-instructions", action="store_true",
                       help="restore the memory and plan files of a crate from another computer (off: they are held back)")
        p.add_argument("--include-plugin-data", action="store_true",
                       help="restore other plugins' data the crate carries, e.g. review boards (off for a crate from another computer)")
        p.add_argument("--relocate", metavar="ROOT", default=None, help="restore the project into ROOT (default: the same paths)")
        p.add_argument("--target-project", type=int, metavar="ID", default=None, help="the existing project that takes the sessions")
        p.add_argument("--skip-conflicts", action="store_true", help="keep a local file that differs from the crate's")

    p = sub.add_parser("setup", help="turn the crate plugin on with its grants and check the primary crates folder")
    _add_host(p, "", "the host")
    common(p)
    p = sub.add_parser("export", help="export a project or session to a crate on a host; prints the bundle id and sha256")
    _add_host(p, "", "the host")
    export_args(p)
    common(p, long_running=True)
    p = sub.add_parser("send", help="download a bundle's crate from host A, upload it to host B, verify the sha256")
    _add_host(p, "from", "host A (the crate's source)")
    _add_host(p, "to", "host B (the destination)")
    p.add_argument("bundle_id")
    common(p)
    p = sub.add_parser("restore", help="plan then restore a crate in the host's primary folder; refuses on blockers")
    _add_host(p, "", "the host")
    p.add_argument("crate_name", help="file name of the crate in the host's primary crates folder")
    restore_args(p)
    common(p, long_running=True)
    p = sub.add_parser("verify", help="check a finished restore's receipt (placed files, sessions, crate sha256)")
    _add_host(p, "", "the host")
    p.add_argument("import_id")
    p.add_argument("--sha256", default=None, help="the crate's sha256; the receipt must name the same crate")
    p.add_argument("--include-project-files", action="store_true", help="fail (7) if project files were asked for but held back")
    p.add_argument("--include-instructions", action="store_true", help="fail (7) if memory and plan files were asked for but held back")
    p.add_argument("--include-plugin-data", action="store_true", help="fail (7) if plugin data was asked for but held back")
    common(p)
    p = sub.add_parser("undo", help="preview, then undo, a finished restore")
    _add_host(p, "", "the host")
    p.add_argument("import_id")
    common(p)
    p = sub.add_parser("cycle", help="export on A, send, restore on B, verify; --undo rolls the restore back")
    _add_host(p, "from", "host A")
    _add_host(p, "to", "host B")
    export_args(p)
    restore_args(p, project_files=False)
    p.add_argument("--undo", action="store_true", help="undo the restore after it verified")
    common(p, long_running=True)
    return parser


def _token_source(args: argparse.Namespace, key: str) -> TokenSource:
    reference = getattr(args, f"{key}token_op")
    if reference:
        return OnePasswordToken(reference)
    return EnvToken(getattr(args, f"{key}token_env") or DEFAULT_TOKEN_ENV)


def default_client_factory(prefix: str, args: argparse.Namespace) -> CrateClient:
    key = f"{prefix}_" if prefix else ""
    return CrateClient(getattr(args, f"{key}url"), _token_source(args, key))


def _options(args: argparse.Namespace) -> flows.ImportOptions:
    return flows.ImportOptions(include_project_files=args.include_project_files, include_instructions=args.include_instructions,
                               include_plugin_data=args.include_plugin_data)


def _run(args: argparse.Namespace, factory: ClientFactory) -> Dict[str, Any]:
    cmd = args.command
    if cmd == "setup":
        return factory("", args).setup()
    if cmd == "send":
        return flows.send_crate(factory("from", args), factory("to", args), args.bundle_id)
    if cmd == "export":
        body = flows.export_body(args.scope, args.target, variant=args.variant, label=args.label,
                                 include_project_files=args.include_project_files)
        return flows.export_crate(factory("", args), body, args.timeout)
    if cmd == "restore":
        return flows.restore_crate(factory("", args), args.crate_name, relocate=args.relocate, target_project=args.target_project,
                                   skip_conflicts=args.skip_conflicts, options=_options(args), timeout=args.timeout)
    if cmd == "verify":
        return flows.verify_import(factory("", args), args.import_id, crate_sha256=args.sha256, asked=_options(args))
    if cmd == "undo":
        return flows.undo_import(factory("", args), args.import_id)
    body = flows.export_body(args.scope, args.target, variant=args.variant, label=args.label,
                             include_project_files=args.include_project_files)
    return flows.cycle(factory("from", args), factory("to", args), body, relocate=args.relocate, target_project=args.target_project,
                       skip_conflicts=args.skip_conflicts, options=_options(args), undo=args.undo, timeout=args.timeout)


def render(command: str, answer: Dict[str, Any]) -> str:
    if command == "setup":
        return f"crate plugin {'enabled' if answer['enabled'] else 'OFF'} ({'changed' if answer['changed'] else 'already set'}), {answer['crates']} crate(s) in the primary folder"
    if command == "export":
        return f"exported {answer['bundle_id']} sha256 {answer['sha256']}"
    if command == "send":
        return f"sent {answer['name']} ({answer['size']} bytes) sha256 {answer['sha256']}"
    if command == "restore":
        r = answer["receipt"]
        return (f"restored {answer['import_id']} ({answer['provenance']}): {r.get('state')}, files written {r.get('files', {}).get('written', 0)}, "
                f"sessions {len(r.get('sessions', []))} asleep")
    if command == "verify":
        line = (f"verified {answer['import_id']}: files written {answer['files_written']} same {answer['files_same']}, "
                f"sessions {answer['sessions']}, rows {answer['rows_inserted']}, warnings {answer['warnings']}")
        held = answer.get("held_back") or []
        if held:
            line += "\nheld back (not restored; add the --include-* flag to bring it): " + "; ".join(
                f"{h['what']} [{h['why']}]" for h in held)
        return line
    if command == "undo":
        undone = answer["result"].get("undo", {})
        return f"undone {answer['import_id']}: files removed {undone.get('files_removed', '?')}, kept {len(undone.get('kept', []))}"
    parts = [render("export", answer["export"]), render("send", answer["send"]), render("restore", answer["restore"]),
             render("verify", answer["verify"])]
    if answer.get("undo"):
        parts.append(render("undo", answer["undo"]))
    return "\n".join(parts)


def main(argv: Optional[Sequence[str]] = None, *, factory: ClientFactory = default_client_factory, out: Optional[TextIO] = None,
         err: Optional[TextIO] = None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        answer = _run(args, factory)
    except CrateScriptError as exc:
        if args.json:
            print(json.dumps(exc.as_json(), default=str), file=out)
        else:
            print(f"error ({type(exc).__name__}, exit {exc.exit_code}): {exc}", file=err)
        return exc.exit_code
    print(json.dumps({"ok": True, **answer}, default=str) if args.json else render(args.command, answer), file=out)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
