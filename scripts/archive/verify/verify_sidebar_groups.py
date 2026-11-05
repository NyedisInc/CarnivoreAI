#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_sidebar_rename import measure_inline_rename  # noqa: E402
from verify_sidebar_sessions import (  # noqa: E402
    ARRANGEMENT_KEY,
    DENSITY_KEY,
    Report,
    assert_viewport,
    open_page,
    serve,
)

ROOT = Path(__file__).resolve().parent.parent


def _arrangement(pinned: list[str], order: list[str], collapsed: list[str] | None = None) -> str:
    import json
    body: dict[str, object] = {"v": 1, "pinned": pinned, "order": order}
    if collapsed is not None:
        body["collapsed"] = collapsed
    return json.dumps(body)


def measure_heading_cluster(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    m = page.evaluate("""() => {
      const q = (s) => document.querySelector(s);
      const r = (e) => e.getBoundingClientRect();
      const title = q('.session-sidebar-title');
      const dens = q('#session-sidebar-density');
      const tools = q('.session-sidebar-tools');
      const acts = q('.session-sidebar-actions');
      return {
        toTitle: r(dens).left - r(title).right,
        toActions: r(acts).left - r(dens).right,
        inTools: tools.contains(dens),
        inActions: acts.contains(dens),
        toolsKids: tools.children.length,
        bars: dens.querySelectorAll('rect').length,
        lines: dens.querySelectorAll('line').length,
      };
    }""")
    rep.check(m["inTools"] and not m["inActions"],
              "ITEM 62: the density control lives in the LIST tools cluster, not panel chrome",
              f"inTools={m['inTools']} inActions={m['inActions']}")
    rep.check(0 < m["toTitle"] <= 16,
              "ITEM 62: it sits right next to the title, not pushed to the far edge",
              f"gap to title={m['toTitle']:.1f}px")
    rep.check(m["toActions"] > m["toTitle"],
              "ITEM 62: and is measurably FARTHER from the pin/close pair than from the title",
              f"to title={m['toTitle']:.1f}px vs to actions={m['toActions']:.1f}px")
    rep.check(m["bars"] == 3 and m["lines"] == 0,
              "ITEM 62: the density glyph is filled bars, not the stroked hamburger",
              f"rects={m['bars']} lines={m['lines']}")
    rep.note(f"the tools cluster holds {m['toolsKids']} control(s); "
             "adding another is one appended sibling")
    page.close()


def measure_empty_pinned_group(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    g = page.evaluate("window.__sidebarMeasure()")
    rep.check(len(g["groups"]) == 0,
              "ITEM 64: nothing pinned means NO group headers, not an empty one",
              f"groups={len(g['groups'])}")
    rep.check(len(g["rows"]) == 9,
              "ITEM 64: and all nine rows still render, ungrouped",
              f"rows={len(g['rows'])}")
    painted = page.evaluate(
        "document.querySelectorAll('.session-sidebar-group__header').length")
    rep.check(painted == 0,
              "ITEM 64: no header element is painted anywhere in the list",
              f"painted={painted}")
    page.close()


def measure_grouped_layout(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {
        DENSITY_KEY: "cozy",
        ARRANGEMENT_KEY: _arrangement(["cloude_fs2", "cloude_asd"], ["cloude_fs2", "cloude_asd"]),
    })
    assert_viewport(page, rep)
    g = page.evaluate("window.__sidebarMeasure()")

    keys = [gr["key"] for gr in g["groups"]]
    rep.check(keys == ["pinned", "other"],
              "ITEM 64: exactly two groups, pinned FIRST",
              f"keys={keys}")

    pinned_g = g["groups"][0]
    other_g = g["groups"][1]
    rep.check(pinned_g["renderedCount"] == 2 and pinned_g["declaredCount"] == 2,
              "ITEM 64: the pinned group holds the two pinned rows",
              f"rendered={pinned_g['renderedCount']} declared={pinned_g['declaredCount']}")
    rep.check(other_g["renderedCount"] == 7,
              "ITEM 64: and the other group holds the remaining seven",
              f"rendered={other_g['renderedCount']}")

    for gr in g["groups"]:
        rep.check(gr["badgeCount"] == gr["renderedCount"],
                  f"ITEM 64: the {gr['key']} header's count matches its rows",
                  f"badge={gr['badgeCount']} rows={gr['renderedCount']}")

    for gr in g["groups"]:
        rep.check(abs(gr["headerHeight"] - 22.0) < 0.5,
                  f"ITEM 64: the {gr['key']} header measures the declared 22px",
                  f"height={gr['headerHeight']:.2f}")
    rep.note("header heights: "
             + ", ".join(f"{gr['key']}={gr['headerHeight']:.2f}px" for gr in g["groups"]))

    pinned_rows = [r for r in g["rows"] if r["pinned"] == "1"]
    other_rows = [r for r in g["rows"] if r["pinned"] == "0"]
    boundary = max(r["bottom"] for r in pinned_rows)
    first_other = min(r["top"] for r in other_rows)
    rep.check(boundary <= first_other,
              "ITEM 64: every pinned row is painted ABOVE every unpinned row",
              f"last pinned bottom={boundary:.2f} <= first other top={first_other:.2f}")
    rep.note(f"BOUNDARY at y={boundary:.2f}px; other group starts at y={first_other:.2f}px")

    rep.check(boundary <= other_g["headerTop"] <= first_other,
              "ITEM 64: the 'other' header is painted IN the seam, between the bands",
              f"header top={other_g['headerTop']:.2f}")

    for gr in g["groups"]:
        rep.check(gr["expanded"] == "true",
                  f"ITEM 64: the {gr['key']} header reports aria-expanded=true when open", "")
        rep.check(gr["controls"] == gr["bodyId"] and bool(gr["bodyId"]),
                  f"ITEM 64: the {gr['key']} header's aria-controls resolves to its body",
                  f"controls={gr['controls']} bodyId={gr['bodyId']}")
    page.close()


def measure_collapse(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {
        DENSITY_KEY: "cozy",
        ARRANGEMENT_KEY: _arrangement(["cloude_fs2"], ["cloude_fs2"]),
    })
    assert_viewport(page, rep)

    before = page.evaluate("window.__sidebarMeasure()")
    rep.check(before["groups"][0]["renderedCount"] == 1,
              "ITEM 64: the pinned group starts open with its row", "")
    open_rot = before["groups"][0]["chevronTransform"]

    page.click('.session-sidebar-group__header[data-group-toggle="pinned"]')
    page.wait_for_timeout(80)
    after = page.evaluate("window.__sidebarMeasure()")
    pinned_g = after["groups"][0]

    rep.check(pinned_g["collapsed"] == "1" and pinned_g["expanded"] == "false",
              "ITEM 64: clicking the header collapses the group, in state AND in aria",
              f"collapsed={pinned_g['collapsed']} expanded={pinned_g['expanded']}")
    rep.check(pinned_g["renderedCount"] == 0,
              "ITEM 64: a collapsed group renders NO rows, not hidden ones",
              f"rows still in DOM={pinned_g['renderedCount']}")
    rep.check(pinned_g["badgeCount"] == 1,
              "ITEM 64: but it still SAYS how many it hides",
              f"badge={pinned_g['badgeCount']}")
    rep.check(len(after["rows"]) == 8,
              "ITEM 64: so the list is one row shorter", f"rows={len(after['rows'])}")

    rep.check(pinned_g["chevronTransform"] != open_rot,
              "ITEM 64: the chevron's COMPUTED transform really changes",
              f"open={open_rot} collapsed={pinned_g['chevronTransform']}")

    stored = page.evaluate(f"localStorage.getItem({ARRANGEMENT_KEY!r})")
    rep.check(stored is not None and "collapsed" in stored and "pinned" in stored,
              "ITEM 64: the fold rides the SAME arrangement key, not a second store",
              f"stored={stored}")
    page.evaluate("window.__reload()")
    page.wait_for_timeout(150)
    reloaded = page.evaluate("window.__sidebarMeasure()")
    rep.check(reloaded["groups"][0]["collapsed"] == "1",
              "ITEM 64: and the fold survives a reload",
              f"collapsed={reloaded['groups'][0]['collapsed']}")
    page.close()


def _row_box(page, name: str) -> dict:
    return page.evaluate(
        "(n) => { const r = document.querySelector("
        "`.session-sidebar-row[data-name=\"${n}\"]`); "
        "if (!r) return null; const b = r.getBoundingClientRect(); "
        "return {x: b.x + b.width / 2, y: b.y + b.height / 2, top: b.top, height: b.height}; }",
        name,
    )


def _drag(page, src_name: str, target_y: float) -> None:
    grip = page.evaluate(
        "(n) => { const g = document.querySelector("
        "`.session-sidebar-row[data-name=\"${n}\"] [data-grip-session]`); "
        "const b = g.getBoundingClientRect(); "
        "return {x: b.x + b.width / 2, y: b.y + b.height / 2}; }",
        src_name,
    )
    page.mouse.move(grip["x"], grip["y"])
    page.mouse.down()
    steps = 8
    for i in range(1, steps + 1):
        page.mouse.move(grip["x"], grip["y"] + (target_y - grip["y"]) * i / steps)
        page.wait_for_timeout(20)
    page.mouse.up()
    page.wait_for_timeout(120)


def measure_drag_across_boundary(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {
        DENSITY_KEY: "cozy",
        ARRANGEMENT_KEY: _arrangement(["cloude_fs2"], ["cloude_fs2"]),
    })
    assert_viewport(page, rep)
    g = page.evaluate("window.__sidebarMeasure()")
    victim = [r for r in g["rows"] if r["pinned"] == "0"][0]["name"]
    pinned_row = _row_box(page, "cloude_fs2")
    _drag(page, victim, pinned_row["top"] + 2)

    after = page.evaluate("window.__sidebarMeasure()")
    moved = [r for r in after["rows"] if r["name"] == victim]
    rep.check(bool(moved) and moved[0]["pinned"] == "1",
              "ITEM 65: dragging a row INTO the pinned group pins it",
              f"{victim} pinned={moved[0]['pinned'] if moved else 'gone'}")
    rep.check(after["groups"][0]["renderedCount"] == 2,
              "ITEM 65: and the pinned group really grew to two rows",
              f"pinned group rows={after['groups'][0]['renderedCount']}")
    stored = page.evaluate(f"localStorage.getItem({ARRANGEMENT_KEY!r})")
    rep.check(stored is not None and victim in stored,
              "ITEM 65: the pin from a DRAG is persisted like any other", "")
    page.close()

    page = open_page(browser, port, {
        DENSITY_KEY: "cozy",
        ARRANGEMENT_KEY: _arrangement(["cloude_fs2"], ["cloude_fs2"]),
    })
    g = page.evaluate("window.__sidebarMeasure()")
    others = [r for r in g["rows"] if r["pinned"] == "0"]
    drop_y = others[-1]["bottom"] - 2
    _drag(page, "cloude_fs2", drop_y)

    after = page.evaluate("window.__sidebarMeasure()")
    moved = [r for r in after["rows"] if r["name"] == "cloude_fs2"]
    rep.check(bool(moved) and moved[0]["pinned"] == "0",
              "ITEM 65: dragging a row OUT of the pinned group unpins it",
              f"cloude_fs2 pinned={moved[0]['pinned'] if moved else 'gone'}")
    rep.check(len(after["groups"]) == 0,
              "ITEM 65: emptying the pinned group removes the headers again",
              f"groups={len(after['groups'])}")
    page.close()


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("CANNOT DETERMINE: playwright is not importable, so no geometry was measured.")
        print("  install with: python3 -m pip install playwright "
              "&& python3 -m playwright install chromium")
        return 2

    httpd, port = serve(ROOT)
    rep = Report()
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--use-mock-keychain"])
            except Exception as exc:  # noqa: BLE001
                print(f"CANNOT DETERMINE: chromium would not launch: {exc}")
                return 2
            try:
                measure_heading_cluster(browser, port, rep)
                measure_empty_pinned_group(browser, port, rep)
                measure_grouped_layout(browser, port, rep)
                measure_collapse(browser, port, rep)
                measure_drag_across_boundary(browser, port, rep)
                measure_inline_rename(browser, port, rep)
            except Exception as exc:  # noqa: BLE001
                print("\n".join(rep.lines))
                print(f"CANNOT DETERMINE: the measurement run did not complete: {exc}")
                return 2
            finally:
                browser.close()
    finally:
        httpd.shutdown()

    print("\n".join(rep.lines))
    if rep.failures:
        print(f"\nFAILED {len(rep.failures)} check(s):")
        for f in rep.failures:
            print(f"  - {f}")
        return 1
    print(f"\nOK: {len(rep.lines)} lines, every measured check held.")
    return 0


if __name__ == "__main__":
    import os as _os
    import sys as _sys

    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from scripts.lib.verify_harness import run_main

    _sys.exit(run_main(main))
