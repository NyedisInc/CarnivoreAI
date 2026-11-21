from __future__ import annotations

import re

from tests.python.design_system._sources import REPO

WEB_SRC = REPO / "web" / "src"
KNOWN: frozenset[str] = frozenset()
SCREEN_TOKEN = re.compile(r"""class\s*=\s*["'][^"']*(?<![\w-])screen(?![\w-])[^"']*["']|class:screen\b""")


def offenders(markup: str) -> list[str]:
    return [m.group(0) for m in SCREEN_TOKEN.finditer(markup)]


def test_scan_goes_red_on_the_old_markup() -> None:
    assert offenders('<div class="screen">') and offenders('<div class="x screen y">') and offenders("<div class:screen>")
    assert not offenders('<div class="screen__body themes-screen">')


def test_no_component_wears_the_legacy_screen_class() -> None:
    files = [p for p in WEB_SRC.rglob("*.svelte") if "test" not in p.name.lower() and "Fixture" not in p.name]
    assert files, "scanned nothing"
    bad = {str(p.relative_to(WEB_SRC)): offenders(p.read_text()) for p in files}
    bad = {k: v for k, v in bad.items() if v and k not in KNOWN}
    assert not bad, f"legacy screen class doubles the docked-sidebar offset inside a frame: {bad}"
