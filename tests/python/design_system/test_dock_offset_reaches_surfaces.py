from __future__ import annotations

import re

from tests.python.design_system._sources import REPO, css_of, top_level_chunks

CSS = REPO / "client" / "css"
SURFACES = ("#launchpad-screen", ".header")
LEFT_PADDING = re.compile(r"padding(?:-left)?\s*:")


def unlayered_surface_rules(css: str) -> list[str]:
    hits = []
    for chunk in top_level_chunks(css):
        if chunk.startswith("@"):
            continue
        selector = chunk.split("{", 1)[0].strip()
        if selector in SURFACES and LEFT_PADDING.search(chunk):
            hits.append(chunk)
    return hits


def load_order() -> list[str]:
    html = (REPO / "client" / "index.html").read_text()
    return re.findall(r'href="/static/css/([\w.-]+\.css)', html)


def test_the_winning_unlayered_surface_padding_reads_the_dock_offset() -> None:
    order = load_order()
    assert "home-bar.css" in order and "ios-chrome.css" in order, "load order not read: scan is blind"
    for surface in SURFACES:
        winner = None
        for name in order:
            for rule in unlayered_surface_rules(css_of(CSS / name)):
                if rule.split("{", 1)[0].strip() == surface:
                    winner = (name, rule)
        assert winner, f"no unlayered padding rule for {surface}: scan is blind"
        assert "--dock-offset" in winner[1], (
            f"{winner[0]} wins the cascade for {surface} over the layered drawer sheet and ignores --dock-offset"
        )


def test_drawer_and_rail_set_the_token() -> None:
    drawer = css_of(CSS / "session-sidebar.css")
    rail = css_of(CSS / "session-sidebar-rail.css")
    assert re.search(r"body\.session-sidebar-pinned\s*\{[^}]*--dock-offset:\s*var\(--sidebar-dock-w\)", drawer)
    assert re.search(r"body\.session-sidebar-railed\s*\{[^}]*--dock-offset:\s*var\(--sidebar-rail-w\)", rail)


def test_layered_sheets_do_not_carry_a_docked_padding_for_the_unlayered_surfaces() -> None:
    for name in ("session-sidebar.css", "session-sidebar-rail.css"):
        css = css_of(CSS / name)
        assert not re.search(r"session-sidebar-(?:pinned|railed)\s+(?:#launchpad-screen|\.header)\s*\{", css), (
            f"{name} pads a surface an unlayered rule outranks; read --dock-offset there instead"
        )


def test_scan_goes_red_on_the_pre_fix_rule() -> None:
    old = "#launchpad-screen { padding: 0; overflow: hidden; }"
    assert [r for r in unlayered_surface_rules(old) if "--dock-offset" not in r]
    assert not unlayered_surface_rules(".screen { padding-left: 0 }")
