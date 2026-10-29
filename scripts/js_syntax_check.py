#!/usr/bin/env python3
"""Syntax check JavaScript files with the parser goal node would actually use.

This script classifies each file first and then checks it with the matching
parser goal: ``node --input-type=module --check`` reading the file on stdin for
a module, ``node --check <file>`` for a classic script. A green result here has
been proved able to go red (see tests/test_js_syntax_check.py, case 4).

Usage::

    python3 scripts/js_syntax_check.py client/js
    python3 scripts/js_syntax_check.py client/js/app.js client/js/i18n

Exit codes:
    0  every file parsed
    1  at least one file failed to parse
    2  could not check: node is missing, or zero files were found

Exit 2 is NOT a pass. A check that looked at nothing has not checked anything.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_ESM_KEYWORD = re.compile(r"^\s*(?:import|export)\b")


def is_es_module(source: str) -> bool:
    in_block = False
    for line in source.splitlines():
        rest = line
        while rest:
            if in_block:
                close = rest.find("*/")
                if close < 0:
                    rest = ""
                    break
                rest = rest[close + 2:]
                in_block = False
                continue
            opener = rest.find("/*")
            if opener < 0:
                break
            head, rest = rest[:opener], rest[opener + 2:]
            if _ESM_KEYWORD.search(head):
                return True
            in_block = True
        if not in_block and rest and _ESM_KEYWORD.search(rest):
            return True
    return False


def collect(paths: list[str]) -> list[Path]:
    found: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            found.add(p)
            continue
        for candidate in p.rglob("*.js"):
            parts = candidate.parts
            if "node_modules" in parts:
                continue
            if "dist" in parts and parts[parts.index("dist") - 1] == "client":
                continue
            found.add(candidate)
    return sorted(found)


def check_one(path: Path, module: bool) -> str | None:
    if module:
        proc = subprocess.run(
            ["node", "--input-type=module", "--check"],
            input=path.read_bytes(),
            capture_output=True,
        )
    else:
        proc = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
        )
    if proc.returncode == 0:
        return None
    err = proc.stderr.decode("utf-8", "replace")
    lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
    for line in lines:
        if "Error:" in line:
            return line
    return lines[-1] if lines else f"node exited {proc.returncode}"


def main(argv: list[str]) -> int:
    if not argv:
        print("js_syntax_check: no paths given", file=sys.stderr)
        return 2
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"js_syntax_check: cannot run node: {exc}", file=sys.stderr)
        return 2

    files = collect(argv)
    if not files:
        print("js_syntax_check: checked no files", file=sys.stderr)
        return 2

    modules = scripts = 0
    failures = 0
    for path in files:
        module = is_es_module(path.read_text(encoding="utf-8", errors="replace"))
        if module:
            modules += 1
        else:
            scripts += 1
        message = check_one(path, module)
        if message is not None:
            failures += 1
            print(f"{path}: {message}")
    print(f"checked {modules} modules, {scripts} scripts")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
