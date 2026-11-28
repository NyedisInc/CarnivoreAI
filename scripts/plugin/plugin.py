#!/usr/bin/env python3
"""The `plugin` command for plugin authors: new, check, pack, test, link.

Usage (from the repo root, with the app's venv)::

    venv/bin/python3 -m scripts.plugin.plugin new clock --template sidecar
    venv/bin/python3 -m scripts.plugin.plugin check ./clock
    venv/bin/python3 -m scripts.plugin.plugin pack ./clock --out ./dist/clock
    venv/bin/python3 -m scripts.plugin.plugin test ./clock
    CARNIVORE_API_TOKEN=... venv/bin/python3 -m scripts.plugin.plugin link ./clock --base http://127.0.0.1:8000

Exit 0 ok, 1 the check or test failed, 2 the tool could not run it (bad arguments, unreadable folder, no server). The tool never writes a
store: `pack` and `new` write only the folder you name, `test` works in a temporary folder, `link` asks the running app to re-sync, and
the app asks the owner again.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.testsrv_client import api  # noqa: E402
from scripts.plugin import check, templates  # noqa: E402
from src.plugins.cli import install_publish, tester as v3_tester  # noqa: E402
from src.plugins.cli.auth_discovery import CliHttpClient  # noqa: E402
from src.plugins.host.sideload_copy import DEV_SKIP_DIRS, copy_tree  # noqa: E402

PASS, FAIL, COULD_NOT = 0, 1, 2
SIDELOAD_PATH = "/api/v1/cplug-owner/sideload"
TOKEN_ENV = "CARNIVORE_API_TOKEN"
NOT_SHIPPED = frozenset({"tests"}) | DEV_SKIP_DIRS


def cmd_new(args: argparse.Namespace) -> int:
    dest = Path(args.dir or args.name).resolve()
    try:
        files = templates.scaffold(dest, args.name, args.template, args.author)
    except templates.TemplateError as exc:
        print(f"plugin new: {exc}", file=sys.stderr)
        return COULD_NOT
    print(f"wrote {len(files)} files to {dest}: " + ", ".join(sorted(files)))
    return PASS


def cmd_check(args: argparse.Namespace) -> int:
    report = check.check_folder(Path(args.folder).resolve())
    for line in report.errors:
        print(f"error:   {line}")
    for line in report.warnings:
        print(f"warning: {line}")
    print("plugin check: " + ("ok" if report.ok else f"{len(report.errors)} error(s)"))
    return PASS if report.ok else FAIL


def cmd_pack(args: argparse.Namespace) -> int:
    source = Path(args.folder).resolve()
    out = Path(args.out).resolve()
    report = check.check_folder(source)
    if not report.ok or report.manifest_v2 is None:
        print("\n".join(f"error: {e}" for e in report.errors), file=sys.stderr)
        return FAIL
    if out.exists():
        print(f"plugin pack: {out} already exists", file=sys.stderr)
        return COULD_NOT
    copy_tree(source, out, skip_dirs=NOT_SHIPPED)
    m = report.manifest_v2
    pkg_id = f"{args.publisher}/{m.id}" if args.publisher else f"local/{m.id}"
    print(f"packed {pkg_id} {m.version} (min app {m.min_app_version or '1.16.0'}) to {out}")
    return PASS


def cmd_test(args: argparse.Namespace) -> int:
    source = Path(args.folder).resolve()
    rep = v3_tester.test_folder(source)
    if rep.unit_output:
        print(rep.unit_output)
    for line in rep.errors:
        print(f"error: {line}")
    if not rep.ok:
        print("plugin test: failed")
        return FAIL
    print("plugin test: ok")
    return PASS


def cmd_link(args: argparse.Namespace) -> int:
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        print(f"plugin link: set {TOKEN_ENV} (a token is never taken on the command line)", file=sys.stderr)
        return COULD_NOT
    body = {"path": str(Path(args.folder).resolve())}
    if args.name:
        body["name"] = args.name
    try:
        answer = api(args.base.rstrip("/"), token, SIDELOAD_PATH, body, "POST")
    except urllib.error.HTTPError as exc:
        print(f"plugin link: the app answered {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}", file=sys.stderr)
        return FAIL
    except (urllib.error.URLError, OSError) as exc:
        print(f"plugin link: cannot reach {args.base}: {exc}", file=sys.stderr)
        return COULD_NOT
    print(json.dumps(answer, indent=2)[:1500])
    return PASS


def cmd_screenshot(args: argparse.Namespace) -> int:
    from scripts.warez_gates import cplug_capture  # noqa: PLC0415

    source = Path(args.folder).resolve()
    out_dir = Path(args.out).resolve() if args.out else source / "screenshots"
    entries = cplug_capture.capture_plugin_screenshots(source, out_dir, force=True)
    if not entries:
        print("plugin screenshot: no visual views/widgets captured (or Playwright Chromium unavailable)", file=sys.stderr)
        return FAIL
    for e in entries:
        print(f"captured {out_dir / e['file']} ({e['w']}x{e['h']}, {e['bytes']} bytes, surface={e.get('surface')})")
    return PASS


def cmd_publish(args: argparse.Namespace) -> int:
    client = CliHttpClient(base_url=args.base) if args.base else CliHttpClient()
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
    ap = argparse.ArgumentParser(prog="plugin", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="write a starter plugin")
    new.add_argument("name")
    new.add_argument("--template", choices=templates.TEMPLATES, default="sidecar")
    new.add_argument("--dir")
    new.add_argument("--author", default="me")
    new.set_defaults(fn=cmd_new)
    chk = sub.add_parser("check", help="schema, id grammar, manifest check, credential-looking names")
    chk.add_argument("folder")
    chk.set_defaults(fn=cmd_check)
    pack = sub.add_parser("pack", help="copy a validated v2 plugin folder for distribution")
    pack.add_argument("folder")
    pack.add_argument("--out", required=True)
    pack.add_argument("--publisher", help="catalog handle; without it the package is a local sideload")
    pack.set_defaults(fn=cmd_pack)
    test = sub.add_parser("test", help="run unit tests and sandbox smoke checks on a temp copy")
    test.add_argument("folder")
    test.set_defaults(fn=cmd_test)
    link = sub.add_parser("link", help="ask the running app to re-sync this folder")
    link.add_argument("folder")
    link.add_argument("--base", default="http://127.0.0.1:8000")
    link.add_argument("--name")
    link.set_defaults(fn=cmd_link)
    shot = sub.add_parser("screenshot", help="capture headless WebP screenshots of a plugin's views/widgets")
    shot.add_argument("folder")
    shot.add_argument("--out", help="output directory (default: <folder>/screenshots)")
    shot.set_defaults(fn=cmd_screenshot)
    pub = sub.add_parser("publish", help="publish a local plugin folder or GitHub owner/repo@tag to Warez")
    pub.add_argument("target", nargs="?", default=None, help="local folder or GitHub owner/repo@tag")
    pub.add_argument("--github", help="GitHub owner/repo[@tag] pointer")
    pub.add_argument("--tag", help="explicit git tag")
    pub.add_argument("--commit-sha", help="40-hex commit SHA to pin")
    pub.add_argument("--subdir", help="relative subfolder inside the GitHub repo")
    pub.add_argument("--kind", help="submission kind (default: cplug)")
    pub.add_argument("--name", help="override submission item name")
    pub.add_argument("--version")
    pub.add_argument("-y", "--yes", action="store_true")
    pub.add_argument("--base", help="override Carnivore server base URL")
    pub.add_argument("--json", action="store_true")
    pub.set_defaults(fn=cmd_publish)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
