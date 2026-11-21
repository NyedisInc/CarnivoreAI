from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

RAW_VALUE_LATER_KINDS = (
    "radius", "line-height", "tracking", "z-index", "duration", "weight", "border-width", "fallback", "color-def",
)
FIRST_MEASURED_KINDS = frozenset(
    {"controls:exempt"} | {f"{prefix}:{kind}" for prefix in ("baseline", "legacy") for kind in RAW_VALUE_LATER_KINDS}
)
FIRST_MEASURED_ROOTS = frozenset({"baseline:src/plugins/", "legacy:js_controls:"})

_HELD_AT: dict[tuple[str, str, str], frozenset[str]] = {}


class HistoryError(RuntimeError):
    pass


def never_measured(window: str) -> bool:
    return False


def windows_of(key: str) -> tuple[str, ...]:
    prefix, kind = key.split(":", 1)[0], key.rsplit(":", 1)[1]
    found = [root for root in sorted(FIRST_MEASURED_ROOTS) if key.startswith(root)]
    if f"{prefix}:{kind}" in FIRST_MEASURED_KINDS:
        found.append(f"{prefix}:{kind}")
    return tuple(found)


def held(keys: Iterable[str]) -> frozenset[str]:
    return frozenset(window for key in keys for window in windows_of(key))


def is_first_measurement(key: str, held_at_start: frozenset[str], measured: Callable[[str], bool]) -> bool:
    return any(window not in held_at_start and not measured(window) for window in windows_of(key))


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise HistoryError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def ever_held(root: Path, rev: str, fixture: str, window: str, parse: Callable[[str], Iterable[str]]) -> bool:
    for sha in _git(root, "log", "--format=%H", rev, "--", fixture).split():
        cache = (str(root), sha, fixture)
        if cache not in _HELD_AT:
            text = _git(root, "show", f"{sha}:{fixture}") if _git(root, "ls-tree", "--name-only", sha, "--", fixture).strip() else ""
            _HELD_AT[cache] = held(parse(text)) if text else frozenset()
        if window in _HELD_AT[cache]:
            return True
    return False
