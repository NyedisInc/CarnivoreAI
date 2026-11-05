from __future__ import annotations

import re
from pathlib import Path

from ._sources import split_selectors

ROOT = Path(__file__).resolve().parents[3]
TARGETS = ("status-led", "status-dot", "session-sidebar-row-model", "kaw-steam")
STATE = re.compile(r":hover|aria-selected|:focus-within")
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
OPT_OUT = ':root[data-row-lights="still"]'
CANCEL = re.compile(r"animation(-play-state)?\s*:\s*(none|paused)")


def offenders(css: str) -> list[str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [
        sel
        for group, body in RULE.findall(css)
        if CANCEL.search(body)
        for sel in split_selectors(group)
        if STATE.search(sel) and not sel.startswith(OPT_OUT) and any(t in sel for t in TARGETS)
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


def test_a_gated_selector_does_not_shield_an_ungated_one_after_it() -> None:
    planted = (
        ':root[data-row-lights="still"] .session-sidebar-row:not(:hover) .status-led,\n'
        ".session-sidebar-row:not(:hover) .status-led::after { animation: none !important; }"
    )
    assert offenders(planted) == [".session-sidebar-row:not(:hover) .status-led::after"]
