#!/usr/bin/env python3
"""The `plugin` command for plugin authors (plugin redesign Stage 1 step 10): new, check, pack, test, link.

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
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.testsrv_client import api  # noqa: E402
from scripts.plugin import check, templates  # noqa: E402
from src.core.catalog import plugin_pack  # noqa: E402
from src.plugins.host import install_gates  # noqa: E402
from src.plugins.runtime import sandbox  # noqa: E402

PASS, FAIL, COULD_NOT = 0, 1, 2
SIDELOAD_PATH = "/api/v1/cplug-owner/sideload"
TOKEN_ENV = "CARNIVORE_API_TOKEN"
PROBE = Path(__file__).with_name("probe.py")
NOT_SHIPPED = frozenset({"tests"})
TEST_TIMEOUT_S = 120


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
    if not report.ok:
        print("\n".join(f"error: {e}" for e in report.errors), file=sys.stderr)
        return FAIL
    if out.exists():
        print(f"plugin pack: {out} already exists", file=sys.stderr)
        return COULD_NOT
    packed = plugin_pack.pack_folder(source, out, args.publisher, NOT_SHIPPED)
    for note in packed.notes:
        print(f"note: {note}")
    print(f"packed {packed.carnivore['id']} {packed.carnivore['version']} (min app {packed.carnivore['min_app_version']}) to {out}")
    return PASS


def _probe(runtime_dir: Path, code_dir: Path, entry: str) -> List[str]:
    done = subprocess.run([sys.executable, "-I", "-B", str(PROBE), str(runtime_dir), str(code_dir), entry],
                          capture_output=True, text=True, timeout=TEST_TIMEOUT_S, check=False, cwd=str(code_dir))
    try:
        return list(json.loads(done.stdout.strip().splitlines()[-1])["problems"])
    except (IndexError, ValueError, KeyError) as exc:
        raise RuntimeError(f"the entry could not be loaded: {done.stderr.strip()[-300:] or 'no output'}") from exc


def _run_own_tests(source: Path, runtime_dir: Path, code_dir: Path) -> Optional[int]:
    if not (source / "tests").is_dir():
        return None
    shutil.copytree(source / "tests", code_dir / "tests")
    inherited = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "COV_CORE_", "COVERAGE_"))}
    env = {**inherited, "PYTHONPATH": os.pathsep.join([str(runtime_dir), str(code_dir)]), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=str(code_dir), env=env,
                          capture_output=True, text=True, timeout=TEST_TIMEOUT_S, check=False)
    print(done.stdout.strip()[-1500:])
    if done.returncode != 0 and done.stderr.strip():
        print(done.stderr.strip()[-1500:])
    return done.returncode


def cmd_test(args: argparse.Namespace) -> int:
    source = Path(args.folder).resolve()
    report = check.check_folder(source)
    if not report.ok:
        print("\n".join(f"error: {e}" for e in report.errors), file=sys.stderr)
        return FAIL
    with tempfile.TemporaryDirectory() as tmp:
        support = Path(tmp) / "support"
        code_dir = support / "plugins" / report.packed.cplug["id"]
        plugin_pack.pack_folder(source, code_dir, "author", NOT_SHIPPED)
        try:
            install_gates.evaluate(f"author/{report.packed.cplug['id']}", code_dir)
        except install_gates.CplugGateRefusal as exc:
            print(f"install gate refused: {exc.code}: {exc.detail}", file=sys.stderr)
            return FAIL
        runtime_dir = Path(tmp) / "runtime"
        shutil.copytree(sandbox.SDK_SOURCE, runtime_dir / sandbox.SDK_PACKAGE, ignore=shutil.ignore_patterns("__pycache__"))
        try:
            problems = _probe(runtime_dir, code_dir, Path(report.packed.cplug["entry"]).with_suffix("").as_posix().replace("/", "."))
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"plugin test: {exc}", file=sys.stderr)
            return FAIL
        for line in problems:
            print(f"error: {line}")
        tests = _run_own_tests(source, runtime_dir, code_dir)
    if problems or tests not in (None, 0):
        print("plugin test: failed")
        return FAIL
    print("plugin test: ok (install gates, entry matches manifest" + ("" if tests is None else ", own tests") + ")")
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="plugin", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="write a starter plugin")
    new.add_argument("name")
    new.add_argument("--template", choices=templates.TEMPLATES, default="sidecar")
    new.add_argument("--dir")
    new.add_argument("--author", default="me")
    new.set_defaults(fn=cmd_new)
    chk = sub.add_parser("check", help="schema, id grammar, pack dry run, credential-looking names")
    chk.add_argument("folder")
    chk.set_defaults(fn=cmd_check)
    pack = sub.add_parser("pack", help="write the exact package the app and the catalog read")
    pack.add_argument("folder")
    pack.add_argument("--out", required=True)
    pack.add_argument("--publisher", help="catalog handle; without it the package is a local sideload")
    pack.set_defaults(fn=cmd_pack)
    test = sub.add_parser("test", help="run the host's install gates and your tests on a temp copy")
    test.add_argument("folder")
    test.set_defaults(fn=cmd_test)
    link = sub.add_parser("link", help="ask the running app to re-sync this folder")
    link.add_argument("folder")
    link.add_argument("--base", default="http://127.0.0.1:8000")
    link.add_argument("--name")
    link.set_defaults(fn=cmd_link)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
