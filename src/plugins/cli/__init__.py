
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import structlog

from src.plugins.cli import checker, dev_runner, install_publish, templates, tester
from src.plugins.cli.auth_discovery import CliHttpClient

PASS, FAIL, COULD_NOT = 0, 1, 2


def _cmd_new(args: argparse.Namespace) -> int:
    if args.dir:
        dest = Path(args.dir).expanduser().resolve()
        plugin_name = args.name
    elif "/" in args.name or "\\" in args.name or args.name.startswith((".", "~")):
        dest = Path(args.name).expanduser().resolve()
        plugin_name = dest.name
    else:
        dest = Path(args.name).resolve()
        plugin_name = args.name
    try:
        files = templates.scaffold(dest, plugin_name, args.template, args.author)
    except templates.TemplateError as exc:
        print(f"plugin new: {exc}", file=sys.stderr)
        return COULD_NOT
    if args.json:
        print(json.dumps({"path": str(dest), "template": args.template, "files": sorted(files)}))
    else:
        print(f"wrote {len(files)} files to {dest}: " + ", ".join(sorted(files)))
    return PASS


def _cmd_check(args: argparse.Namespace) -> int:
    report = checker.check_folder(Path(args.folder).resolve())
    if args.json:
        print(json.dumps({"ok": report.ok, "errors": report.errors, "warnings": report.warnings}))
    else:
        for line in report.errors:
            print(f"error:   {line}")
        for line in report.warnings:
            print(f"warning: {line}")
        print("plugin check: " + ("ok" if report.ok else f"{len(report.errors)} error(s)"))
    return PASS if report.ok else FAIL


def _cmd_test(args: argparse.Namespace) -> int:
    rep = tester.test_folder(
        Path(args.folder).resolve(),
        unit_only=args.unit_only,
        smoke_only=args.smoke_only,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "ok": rep.ok,
                    "errors": rep.errors,
                    "warnings": rep.warnings,
                    "smoke": rep.smoke_summary,
                }
            )
        )
    else:
        if rep.unit_output:
            print(rep.unit_output)
        for line in rep.errors:
            print(f"error: {line}", file=sys.stderr)
        print("plugin test: ok" if rep.ok else "plugin test: failed")
    return PASS if rep.ok else FAIL


def _cmd_dev(args: argparse.Namespace) -> int:
    client = CliHttpClient(base_url=args.base) if args.base else None
    return dev_runner.run_dev(Path(args.folder).resolve(), client=client, debounce_ms=args.debounce_ms)


def _cmd_install(args: argparse.Namespace) -> int:
    client = CliHttpClient(base_url=args.base) if args.base else None
    return install_publish.run_install(
        args.source,
        client=client,
        mode=args.source_kind,
        assume_yes=args.yes,
        enable=not args.no_enable,
        as_json=args.json,
    )


def _cmd_publish(args: argparse.Namespace) -> int:
    client = CliHttpClient(base_url=args.base) if args.base else None
    target = args.target if args.target is not None else ("." if not args.github else "")
    return install_publish.run_publish(
        target,
        version=args.version,
        github=args.github,
        tag=args.tag,
        commit_sha=args.commit_sha,
        subdir=args.subdir,
        kind=args.kind,
        name=args.name,
        client=client,
        assume_yes=args.yes,
        as_json=args.json,
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="carnivore plugin", description="Carnivore plugin developer CLI")
    sub = ap.add_subparsers(dest="subcommand", required=True)

    p_new = sub.add_parser("new", help="scaffold a new v2 plugin")
    p_new.add_argument("name")
    p_new.add_argument("--template", choices=templates.TEMPLATES, default=templates.DEFAULT_TEMPLATE)
    p_new.add_argument("--dir")
    p_new.add_argument("--author", default=templates.DEFAULT_AUTHOR)
    p_new.add_argument("--json", action="store_true")
    p_new.set_defaults(fn=_cmd_new)

    p_chk = sub.add_parser("check", help="validate manifest, files, and secret hygiene")
    p_chk.add_argument("folder", nargs="?", default=".")
    p_chk.add_argument("--json", action="store_true")
    p_chk.set_defaults(fn=_cmd_check)

    p_tst = sub.add_parser("test", help="run manifest check, unit tests, and sandbox smoke test")
    p_tst.add_argument("folder", nargs="?", default=".")
    p_tst.add_argument("--unit-only", action="store_true")
    p_tst.add_argument("--smoke-only", action="store_true")
    p_tst.add_argument("--json", action="store_true")
    p_tst.set_defaults(fn=_cmd_test)

    p_dev = sub.add_parser("dev", help="watch plugin folder for <300ms hot reload with Dev Trust Lease")
    p_dev.add_argument("folder", nargs="?", default=".")
    p_dev.add_argument("--base", help="override Carnivore server base URL")
    p_dev.add_argument("--debounce-ms", type=int, default=dev_runner.DEBOUNCE_MS_DEFAULT)
    p_dev.set_defaults(fn=_cmd_dev)

    p_inst = sub.add_parser("install", help="install from local dir, GitHub owner/repo, or Warez catalog")
    p_inst.add_argument("source")
    p_inst.add_argument("--from", dest="source_kind", choices=("auto", "local", "github", "warez"), default="auto")
    p_inst.add_argument("-y", "--yes", action="store_true")
    p_inst.add_argument("--no-enable", action="store_true")
    p_inst.add_argument("--base", help="override Carnivore server base URL")
    p_inst.add_argument("--json", action="store_true")
    p_inst.set_defaults(fn=_cmd_install)

    p_pub = sub.add_parser("publish", help="run check+test preflight and publish a folder or owner/repo@tag to Warez")
    p_pub.add_argument("target", nargs="?", default=None, help="local folder or GitHub owner/repo@tag")
    p_pub.add_argument("--github", help="GitHub owner/repo[@tag] pointer")
    p_pub.add_argument("--tag", help="explicit git tag for GitHub submission")
    p_pub.add_argument("--commit-sha", help="40-hex commit SHA to pin for GitHub submission")
    p_pub.add_argument("--subdir", help="relative subfolder inside the GitHub repository")
    p_pub.add_argument("--kind", help="submission kind (default: cplug)")
    p_pub.add_argument("--name", help="override submission item name")
    p_pub.add_argument("--version")
    p_pub.add_argument("-y", "--yes", action="store_true")
    p_pub.add_argument("--base", help="override Carnivore server base URL")
    p_pub.add_argument("--json", action="store_true")
    p_pub.set_defaults(fn=_cmd_publish)

    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    was_configured = structlog.is_configured()
    prev_cfg = structlog.get_config() if was_configured else None
    cfg: Dict[str, Any] = {
        "logger_factory": structlog.PrintLoggerFactory(file=sys.stderr),
    }
    if getattr(args, "json", False):
        cfg["wrapper_class"] = structlog.make_filtering_bound_logger(logging.WARNING)
    structlog.configure(**cfg)
    try:
        return int(args.fn(args))
    finally:
        if was_configured and prev_cfg is not None:
            structlog.configure(**prev_cfg)
        else:
            structlog.reset_defaults()
