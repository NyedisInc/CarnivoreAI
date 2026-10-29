
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAUSE = ROOT / "client" / "css" / "animation-pause.css"
TEXT_ONLY = {"oc-tfw-measure", "oc-tf-labels-measure"}
RULE = re.compile(r"\.([\w-]*measure[\w-]*)\s*\{([^}]*)\}")


def measure_classes() -> set[str]:
    found: set[str] = set()
    for svelte in (ROOT / "web" / "src").rglob("*.svelte"):
        for name, body in RULE.findall(svelte.read_text()):
            if re.search(r"visibility:\s*hidden", body):
                found.add(name)
    return found


def cover_lists(css: str) -> list[str]:
    return re.findall(r":is\(([^)]*)\)", css)


def check(css: str) -> list[str]:
    lists = cover_lists(re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    problems = [] if len(lists) >= 3 else [f"only {len(lists)} cover lists"]
    for name in sorted(measure_classes() - TEXT_ONLY):
        problems += [f".{name} missing from list {i}" for i, lst in enumerate(lists) if f".{name}" not in lst]
    return problems


def test_measure_copies_are_paused_in_every_cover_list() -> None:
    assert "oc-tf-measure" in measure_classes(), "found no measuring copy: the scan looked at nothing"
    assert check(PAUSE.read_text()) == []


def test_old_stylesheet_fails() -> None:
    old = (ROOT / "tests" / "fixtures" / "animation-pause.before-1821.css").read_text()
    assert check(old) != []
