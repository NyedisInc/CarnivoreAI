#!/usr/bin/env python3
"""Decide whether a merge's changed files need a full app restart, or can be
synced into the running local install with no restart at all.

THE RULE, TWO STAGES, DENYLIST FIRST.

An empty path list is not a legitimate "nothing changed" answer here: the
caller could not read a diff, which is "could not determine" and must never
be read as a pass. `classify_paths([])` raises `CouldNotDetermine`; the CLI
translates that to exit 2, matching every other "could not determine" gate
in this codebase (`scripts/run_test_tier.py`, `scripts/web-build-check.sh`).

Example:
    >>> classify_paths(["client/js/app.js", "docs/DECISIONS.md"])
    'hot-sync'
    >>> classify_paths(["src/core/session_manager.py"])
    'restart'
"""

from __future__ import annotations

import sys
from typing import Iterable, Literal

Decision = Literal["hot-sync", "restart"]


class CouldNotDetermine(Exception):
    pass


RESTART_PREFIXES: tuple[str, ...] = (
    "src/",
    "macOS/",
)

RESTART_FILENAME_PREFIXES: tuple[str, ...] = ("requirements",)

RESTART_EXACT_FILES: frozenset[str] = frozenset(
    {
        "config.example.json",
        ".env.example",
        "setup_auth.py",
        "nuke.sh",
        "scripts/session_journal.py",
    }
)

HOT_SYNC_PREFIXES: tuple[str, ...] = (
    "client/",
    "docs/",
    "scripts/",
    "tests/",
    ".claude/",
    ".github/",
    "design/",
)

HOT_SYNC_EXACT_FILES: frozenset[str] = frozenset(
    {
        "CLAUDE.md",
        "AGENTS.md",
        "TODO.md",
        "troubleshooting.md",
    }
)


def _is_restart_trigger(path: str) -> bool:
    if path in RESTART_EXACT_FILES:
        return True
    if any(path.startswith(prefix) for prefix in RESTART_PREFIXES):
        return True
    filename = path.rsplit("/", 1)[-1]
    return any(filename.startswith(prefix) for prefix in RESTART_FILENAME_PREFIXES)


def _is_hot_sync_eligible(path: str) -> bool:
    if path in HOT_SYNC_EXACT_FILES:
        return True
    return any(path.startswith(prefix) for prefix in HOT_SYNC_PREFIXES)


def classify_paths(paths: Iterable[str]) -> Decision:
    cleaned = [p.strip() for p in paths if p.strip()]
    if not cleaned:
        raise CouldNotDetermine("no changed paths given - could not determine a diff")
    if any(_is_restart_trigger(p) for p in cleaned):
        return "restart"
    if all(_is_hot_sync_eligible(p) for p in cleaned):
        return "hot-sync"
    return "restart"


def _cli_classify() -> int:
    lines = sys.stdin.read().splitlines()
    try:
        decision = classify_paths(lines)
    except CouldNotDetermine as exc:
        print(f"could not determine: {exc}", file=sys.stderr)
        return 2
    print(decision)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] != "classify":
        print("usage: refresh_decision.py classify   (paths on stdin, one per line)", file=sys.stderr)
        return 2
    return _cli_classify()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
