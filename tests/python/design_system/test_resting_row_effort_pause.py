
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAUSE = ROOT / "client" / "css" / "resting-row-effort.css"
SOURCES = [ROOT / "client" / "css" / n for n in ("effort-level.css", "session-sidebar-row-controls.css")]
GUARD = ':not([aria-selected="true"], :hover, :focus-within)'
RULE = re.compile(r"([^{}]+)\{([^}]*)\}")


def strip(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def kind(selector: str) -> str:
    spark = "spark-" if "__spark" in selector else ""
    for pseudo in ("before", "after"):
        if selector.strip().endswith(f"::{pseudo}") and "effort-fx" not in selector:
            return spark + pseudo
    return "svg" if selector.strip().endswith("> svg") else "self"


def animated_kinds() -> set[str]:
    found: set[str] = set()
    for src in SOURCES:
        for sel, body in RULE.findall(strip(src.read_text())):
            if not re.search(r"animation(-name)?:\s*(?!none)[\w-]", body):
                continue
            for one in sel.split(","):
                if "session-sidebar-row-model" in one and "effort-fx" not in one and not one.lstrip().startswith(":root"):
                    found.add(kind(one))
    return found


def check(css: str) -> list[str]:
    css = re.sub(r"@layer\s+legacy\s*\{", "", strip(css))
    problems: list[str] = []
    covered: set[str] = set()
    for sel, body in RULE.findall(css):
        if GUARD in sel and "animation: none" in body:
            covered |= {kind(s) for s in sel.split(",") if "session-sidebar-row-model" in s}
        if GUARD in sel and ".effort-fx" in sel and "display: none" in body:
            covered.add("fx")
    problems += [f"{k} has no resting rule" for k in sorted(animated_kinds() - covered)]
    if "fx" not in covered:
        problems.append("sheen windows not hidden on a resting row")
    return problems


def test_resting_rows_are_covered_and_active_rows_excluded() -> None:
    assert animated_kinds() >= {"svg", "before", "after", "spark-before", "spark-after"}, "the scan looked at nothing"
    assert check(PAUSE.read_text()) == []


def test_old_stylesheet_fails() -> None:
    old = subprocess.run(["git", "show", "52cdf3124^:client/css/animation-pause.css"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert check(old) != []
