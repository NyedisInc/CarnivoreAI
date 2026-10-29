from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGETS = ("status-led", "status-dot", "session-sidebar-row-model", "kaw-steam")
STATE = re.compile(r":hover|aria-selected|:focus-within")
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
CANCEL = re.compile(r"animation(-play-state)?\s*:\s*(none|paused)")


def offenders(css: str) -> list[str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [
        sel.strip()
        for sel, body in RULE.findall(css)
        if CANCEL.search(body) and STATE.search(sel) and any(t in sel for t in TARGETS)
    ]


def test_no_stylesheet_cancels_row_spinners_by_row_state() -> None:
    bad = []
    for base in ("client/css", "web/src"):
        for f in (ROOT / base).rglob("*"):
            if f.suffix in (".css", ".svelte"):
                bad += [f"{f.relative_to(ROOT)}: {s}" for s in offenders(f.read_text())]
    assert not bad, "row spinners must run on every row:\n  " + "\n  ".join(bad)


def test_negative_control_catches_a_planted_rule() -> None:
    planted = ".session-sidebar-row:not(:hover):not([aria-selected='true']) .status-led { animation: none !important; }"
    assert offenders(planted)
    assert not offenders(".status-led { animation: x 1s infinite; }")
