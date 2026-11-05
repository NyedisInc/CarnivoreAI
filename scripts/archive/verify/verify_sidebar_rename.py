#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_sidebar_sessions import (  # noqa: E402
    DENSITY_KEY,
    Report,
    assert_viewport,
    open_page,
)


def measure_inline_rename(browser, port: int, rep: Report) -> None:
    name_sel = '.session-sidebar-row[data-name="cloude_fstest"] .session-sidebar-row-name'

    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    g = page.evaluate("window.__sidebarMeasure()")
    states = set(g["renameStates"])
    rep.check(states == {"renameable", "unavailable", "unknown"},
              "ITEM 66: all THREE rename states are rendered, including CANNOT DETERMINE",
              f"states={sorted(states)}")
    rep.note(f"rename states on screen: {sorted(states)}")
    unknown_rows = [r for r, s in zip(g["rows"], g["renameStates"]) if s == "unknown"]
    rep.check(len(unknown_rows) == 1,
              "ITEM 66: a null ownership stays UNKNOWN rather than becoming 'external'",
              f"unknown rows={[r['name'] for r in unknown_rows]}")
    page.close()

    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    before = page.evaluate("window.__sidebarMeasure()")
    before_h = [r for r in before["rows"] if r["name"] == "cloude_fstest"][0]["height"]
    page.dblclick(name_sel)
    page.wait_for_timeout(150)
    g2 = page.evaluate("window.__sidebarMeasure()")
    rep.check(g2["rename"] is not None,
              "ITEM 66: double-click on a renameable row opens the editor", "")
    if g2["rename"]:
        rep.check(g2["rename"]["focused"] is True,
                  "ITEM 66: the editor takes real DOM focus", "")
        rep.check(g2["rename"]["value"] == "fstest",
                  "ITEM 66: and starts with what the row DISPLAYS in it",
                  f"value={g2['rename']['value']!r}")
        rep.check(g2["rename"]["maxlength"] == "200",
                  "ITEM 66: the editor accepts a LABEL's length, not a tmux name's",
                  f"maxlength={g2['rename']['maxlength']!r}")
        rep.check(abs(g2["rename"]["rowHeight"] - before_h) < 1.0,
                  "ITEM 66: opening the editor does NOT change the row height",
                  f"before={before_h:.2f} during={g2['rename']['rowHeight']:.2f}")
        rep.check(g2["rename"]["width"] > 40,
                  "ITEM 66: the input has real painted width",
                  f"width={g2['rename']['width']:.2f}")
    open_panel = page.evaluate(
        "document.getElementById('session-sidebar-panel').getAttribute('aria-hidden')")
    rep.check(open_panel != "true",
              "ITEM 66: the panel is still open after the double-click",
              f"panel aria-hidden={open_panel}")
    rep.check(g2["switchCount"] == 0,
              "ITEM 66: the first click of the double-click did NOT switch conversation",
              f"switches={g2['switchCount']}")

    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.type("escape_should_discard")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    g3 = page.evaluate("window.__sidebarMeasure()")
    rep.check(g3["rename"] is None, "ITEM 66: Escape closes the editor", "")
    rep.check(any(r["displayName"] == "fstest" for r in g3["rows"]),
              "ITEM 66: and the original name is restored",
              f"shown={[r['displayName'] for r in g3['rows']][:3]}")
    rep.check(not any(r["displayName"] == "escape_should_discard" for r in g3["rows"]),
              "ITEM 66: Escape DISCARDS the typed name rather than committing it", "")
    page.close()

    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    page.dblclick(name_sel)
    page.wait_for_timeout(150)
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.type("renamed_ok")
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    g4 = page.evaluate("window.__sidebarMeasure()")
    rep.check(g4["rename"] is None, "ITEM 66: Enter closes the editor", "")
    rep.check(any(r["displayName"] == "renamed_ok" for r in g4["rows"]),
              "ITEM 66: Enter COMMITS the new name into the row",
              f"shown={[r['displayName'] for r in g4['rows']][:3]}")
    rep.check(all(r["name"] != "renamed_ok" for r in g4["rows"]),
              "ITEM 66: and the TMUX HANDLE did not move - a rename writes a label",
              f"names={[r['name'] for r in g4['rows']][:3]}")
    shown = [r for r in g4["rows"] if r["displayName"] == "renamed_ok"]
    rep.check(bool(shown) and shown[0]["displayWidth"] > 4,
              "ITEM 66: and the committed name occupies real painted width",
              f"width={shown[0]['displayWidth'] if shown else 'no row'}")
    page.close()

    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    page.evaluate("window.__renameShouldFail = true")
    page.dblclick(name_sel)
    page.wait_for_timeout(150)
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.type("taken_name")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    g5 = page.evaluate("window.__sidebarMeasure()")
    rep.check(any(r["displayName"] == "fstest" for r in g5["rows"]),
              "ITEM 66: a FAILED rename restores the previous name",
              f"shown={[r['displayName'] for r in g5['rows']][:3]}")
    rep.check(not any(r["displayName"] == "taken_name" for r in g5["rows"]),
              "ITEM 66: and the rejected name is nowhere on screen", "")
    rep.check(g5["rename"] is not None,
              "ITEM 66: a failed rename leaves the editor OPEN to be corrected",
              f"rename={g5['rename']}")
    if g5["rename"]:
        rep.check(g5["rename"]["value"] == "taken_name",
                  "ITEM 66: with the rejected text still in it, not cleared",
                  f"value={g5['rename']['value']!r}")
        rep.check("rename failed" in g5["rename"]["error"],
                  "ITEM 66: and the reason shown NEXT TO the input, not only announced",
                  f"error={g5['rename']['error']!r}")
    page.close()

    label = 'Media Compression: v1.2 "final" $5'
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    page.evaluate("(v) => window.__seedLabel('cloude_fstest', v)", label)
    page.evaluate("window.SessionSidebar._lastSig = null")
    page.evaluate("window.SessionSidebar._fetchAndRender()")
    page.wait_for_timeout(250)

    gl = page.evaluate("window.__sidebarMeasure()")
    rep.check(any(r["displayName"] == label for r in gl["rows"]),
              "ITEM 66: a labelled session RENDERS its label, not its tmux handle",
              f"shown={[r['displayName'] for r in gl['rows']][:3]}")
    rep.check(any(r["name"] == "cloude_fstest" for r in gl["rows"]),
              "ITEM 66: while data-name still carries the handle everything keys on",
              f"names={[r['name'] for r in gl['rows']][:3]}")

    page.dblclick(name_sel)
    page.wait_for_timeout(150)
    gl2 = page.evaluate("window.__sidebarMeasure()")
    rep.check(gl2["rename"] is not None and gl2["rename"]["value"] == label,
              "ITEM 66: and the editor OPENS ON THE LABEL, not on the handle",
              f"value={(gl2['rename'] or {}).get('value')!r}")

    page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    stored = page.evaluate("window.__lastRenameValue || null")
    calls = page.evaluate("window.__renameCallCount || 0")
    rep.check(calls == 0 and stored is None,
              "ITEM 66: dismissing the editor UNCHANGED writes nothing at all",
              f"calls={calls} stored={stored!r}")
    g_after = page.evaluate("window.__sidebarMeasure()")
    rep.check(any(r["displayName"] == label for r in g_after["rows"]),
              "ITEM 66: so the label the user typed is still on screen afterwards",
              f"shown={[r['displayName'] for r in g_after['rows']][:3]}")
    page.close()

    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    page.evaluate("(v) => window.__seedLabel('cloude_fstest', v)", label)
    page.evaluate("window.SessionSidebar._lastSig = null")
    page.evaluate("window.SessionSidebar._fetchAndRender()")
    page.wait_for_timeout(250)
    page.dblclick(name_sel)
    page.wait_for_timeout(150)
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.type("Archive Sweep: nightly")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    stored = page.evaluate("window.__lastRenameValue || null")
    rep.check(stored == "Archive Sweep: nightly",
              "ITEM 66: a label with a space and a colon reaches the server VERBATIM",
              f"stored={stored!r}")
    rep.check(not (stored or "").startswith("cloude_"),
              "ITEM 66: and no tmux handle was ever promoted into a stored label",
              f"stored={stored!r}")
    g_edit = page.evaluate("window.__sidebarMeasure()")
    rep.check(any(r["displayName"] == "Archive Sweep: nightly" for r in g_edit["rows"]),
              "ITEM 66: and the row RENDERS the new label",
              f"shown={[r['displayName'] for r in g_edit['rows']][:3]}")
    rep.check(any(r["name"] == "cloude_fstest" for r in g_edit["rows"]),
              "ITEM 66: with the tmux handle STILL unmoved after a successful rename",
              f"names={[r['name'] for r in g_edit['rows']][:3]}")
    page.close()

    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    g6 = page.evaluate("window.__sidebarMeasure()")
    blocked = [(r, s) for r, s in zip(g6["rows"], g6["renameStates"]) if s != "renameable"]
    row, state = blocked[0]
    page.dblclick(
        f'.session-sidebar-row[data-name="{row["name"]}"] .session-sidebar-row-name')
    page.wait_for_timeout(200)
    g7 = page.evaluate("window.__sidebarMeasure()")
    rep.check(g7["rename"] is None,
              "ITEM 66: a row that cannot be renamed opens NO editor",
              f"state={state}")
    rep.check(bool(g7["live"]),
              "ITEM 66: and it SAYS why rather than doing nothing",
              f"live={g7['live']!r}")
    page.close()
