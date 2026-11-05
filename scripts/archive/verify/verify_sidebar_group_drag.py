#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_sidebar_sessions import (  # noqa: E402
    ARRANGEMENT_KEY,
    DENSITY_KEY,
    Report,
    assert_viewport,
    open_page,
    serve,
)

ROOT = Path(__file__).resolve().parent.parent

THEMES = ("terminal", "dracula")


def _theme_vars(name: str) -> dict:
    manifest = json.loads(
        (ROOT / "client/css/themes" / name / "theme.json").read_text()
    )
    return manifest.get("cssVars") or {}


def _apply_theme(page, name: str) -> None:
    page.evaluate(
        "(vars) => { for (const k of Object.keys(vars)) "
        "document.documentElement.style.setProperty(k, vars[k]); }",
        _theme_vars(name),
    )


def assert_visible(page, rep: Report) -> None:
    hidden = page.evaluate("document.hidden")
    if hidden:
        raise RuntimeError(
            "document.hidden is true: the render loop is suspended and every "
            "rect below would be a measurement of an unpainted page"
        )
    rep.check(not hidden, "the page is VISIBLE, so its rects are real",
              f"document.hidden={hidden}")


def _seed(page, groups: list[dict]) -> None:
    page.evaluate("(defs) => window.__seedGroups(defs)", groups)
    page.evaluate(
        "async () => { window.SessionSidebarGroupStore.apply(await window.API.listSessionGroups());"
        " window.SessionSidebar.repaint(); }"
    )
    page.wait_for_function(
        "() => document.querySelectorAll('.session-sidebar-group[data-group]').length > 0",
        timeout=5000,
    )


def _bands(page) -> dict:
    return page.evaluate("""() => {
      const list = document.getElementById('session-sidebar-list');
      const bands = {};
      for (const g of list.querySelectorAll('.session-sidebar-group[data-group]')) {
        const b = g.getBoundingClientRect();
        bands[g.getAttribute('data-group')] = {
          top: b.top, bottom: b.bottom, left: b.left, right: b.right,
          height: b.height, width: b.width,
          count: Number(g.getAttribute('data-count')),
        };
      }
      const rows = {};
      for (const r of list.querySelectorAll('.session-sidebar-row')) {
        const owner = r.closest('.session-sidebar-group[data-group]');
        const b = r.getBoundingClientRect();
        rows[r.dataset.name] = {
          band: owner ? owner.getAttribute('data-group') : null,
          top: b.top, bottom: b.bottom, left: b.left, right: b.right,
          height: b.height, width: b.width,
        };
      }
      return { bands, rows, live: (document.getElementById('session-sidebar-live') || {}).textContent || '' };
    }""")


def _band_y(page, band_key: str):
    return page.evaluate(
        """(key) => {
          const g = document.querySelector(
            `.session-sidebar-group[data-group="${key}"]`);
          if (!g) return null;
          const b = g.getBoundingClientRect();
          return b.top + b.height / 2;
        }""",
        band_key,
    )


def _drag_into(page, src_name: str, band_key: str) -> None:
    grip = page.evaluate(
        """(name) => {
          const row = document.querySelector(
            `.session-sidebar-row[data-name="${name}"]`);
          if (!row) return null;
          const g = row.querySelector('[data-grip-session]');
          if (!g) return null;
          const b = g.getBoundingClientRect();
          return { x: b.left + b.width / 2, y: b.top + b.height / 2 };
        }""",
        src_name,
    )
    if not grip:
        raise RuntimeError(f"cannot drag {src_name}: its grip is not rendered")

    page.mouse.move(grip["x"], grip["y"])
    page.mouse.down()
    page.mouse.move(grip["x"], grip["y"] + 8)
    page.mouse.move(grip["x"], grip["y"] + 12)

    target_y = _band_y(page, band_key)
    if target_y is None:
        page.mouse.up()
        raise RuntimeError(f"cannot drag into {band_key}: that band is not rendered")
    start_y = grip["y"] + 12
    steps = 14
    for i in range(1, steps + 1):
        page.mouse.move(grip["x"], start_y + (target_y - start_y) * i / steps)
        refreshed = _band_y(page, band_key)
        if refreshed is not None:
            target_y = refreshed
    page.mouse.move(grip["x"], target_y)
    page.mouse.up()
    page.wait_for_timeout(150)


def measure_drag_between_groups(browser, port: int, rep: Report, theme: str) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    assert_visible(page, rep)
    _apply_theme(page, theme)
    _seed(page, [
        {"uuid": "ga", "name": "work", "members": ["cloude_fstest"]},
        {"uuid": "gb", "name": "infra", "members": []},
    ])

    before = _bands(page)
    start = before["rows"].get("cloude_fstest", {}).get("band")
    rep.check(start == "g:ga",
              f"[{theme}] the row starts inside the band its membership names",
              f"band={start}")
    rep.check(before["bands"].get("g:gb", {}).get("height", 0) > 0,
              f"[{theme}] an EMPTY group is drawn with real painted height, "
              "so it can be dropped into",
              f"empty band height={before['bands'].get('g:gb', {}).get('height')}")

    _drag_into(page, "cloude_fstest", "g:gb")
    after = _bands(page)
    landed = after["rows"].get("cloude_fstest", {})

    rep.check(landed.get("band") == "g:gb",
              f"[{theme}] THE ROW IS NOW DRAWN INSIDE THE OTHER GROUP",
              f"band before={start} after={landed.get('band')}")
    band_box = after["bands"].get("g:gb", {})
    inside = (band_box and landed
              and landed["top"] >= band_box["top"] - 1
              and landed["bottom"] <= band_box["bottom"] + 1)
    rep.check(bool(inside),
              f"[{theme}] and its painted rect lies INSIDE that group's painted rect",
              f"row=({landed.get('top')},{landed.get('bottom')}) "
              f"band=({band_box.get('top')},{band_box.get('bottom')})")
    rep.check(landed.get("height", 0) > 0 and landed.get("width", 0) > 0,
              f"[{theme}] the moved row still paints a non-zero box",
              f"{landed.get('width')}x{landed.get('height')}")
    rep.check(after["bands"].get("g:ga", {}).get("count") == 0,
              f"[{theme}] the source group's rendered count dropped to 0",
              f"count={after['bands'].get('g:ga', {}).get('count')}")
    rep.check("infra" in after.get("live", ""),
              f"[{theme}] the move is ANNOUNCED, not only drawn",
              f"live={after.get('live')!r}")
    page.close()


def measure_row_follows_the_finger(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    assert_visible(page, rep)
    _seed(page, [
        {"uuid": "ga", "name": "work", "members": ["cloude_fstest"]},
        {"uuid": "gb", "name": "infra", "members": []},
    ])
    grip = page.evaluate(
        """() => {
          const row = document.querySelector(
            '.session-sidebar-row[data-name="cloude_fstest"]');
          const g = row.querySelector('[data-grip-session]');
          const b = g.getBoundingClientRect();
          return { x: b.left + b.width / 2, y: b.top + b.height / 2 };
        }"""
    )
    page.mouse.move(grip["x"], grip["y"])
    page.mouse.down()
    page.mouse.move(grip["x"], grip["y"] + 8)
    page.mouse.move(grip["x"], grip["y"] + 12)
    for _ in range(6):
        target = _band_y(page, "g:gb")
        if target is None:
            break
        page.mouse.move(grip["x"], target)
    page.wait_for_timeout(80)

    mid = page.evaluate(
        """() => {
          const r = document.querySelector(
            '.session-sidebar-row[data-name="cloude_fstest"]');
          if (!r) return null;
          const owner = r.closest('.session-sidebar-group[data-group]');
          return owner ? owner.getAttribute('data-group') : null;
        }"""
    )
    rep.check(mid == "g:gb",
              "MID-DRAG, pointer still down: the row is ALREADY drawn in the "
              "target group, so it follows the finger rather than teleporting "
              "on release",
              f"band while dragging={mid}")
    page.mouse.up()
    page.wait_for_timeout(150)
    page.close()


def measure_drag_within_band_is_a_no_op(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    assert_visible(page, rep)
    _seed(page, [
        {"uuid": "ga", "name": "work",
         "members": ["cloude_fstest", "cloude_Test", "cloude_asd"]},
        {"uuid": "gb", "name": "infra", "members": []},
    ])
    before = _bands(page)
    _drag_into(page, "cloude_fstest", "g:ga")
    after = _bands(page)
    rep.check(after["rows"]["cloude_fstest"]["band"] == "g:ga"
              == before["rows"]["cloude_fstest"]["band"],
              "CONTROL: a drag inside the row's OWN band leaves its band alone",
              f"before={before['rows']['cloude_fstest']['band']} "
              f"after={after['rows']['cloude_fstest']['band']}")
    rep.check(after["bands"]["g:gb"]["count"] == 0,
              "CONTROL: and nothing landed in the group it was never dragged to",
              f"count={after['bands']['g:gb']['count']}")
    page.close()


def measure_non_drag_parity(browser, port: int, rep: Report, theme: str) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    assert_visible(page, rep)
    _apply_theme(page, theme)
    _seed(page, [
        {"uuid": "ga", "name": "work", "members": ["cloude_fstest"]},
        {"uuid": "gb", "name": "infra", "members": []},
    ])

    rep.check(
        page.query_selector('[data-row-menu]') is None,
        f"[{theme}] no row paints an overflow menu trigger any more",
        "kebab absent" if page.query_selector('[data-row-menu]') is None
        else "a kebab is still painted")
    page.evaluate("""() => {
      const row = document.querySelector(
        '.session-sidebar-row[data-name="cloude_fstest"]');
      row.focus();
    }""")
    page.keyboard.press("g")
    page.wait_for_selector('#item-menu-host [role="menu"]', timeout=4000)
    rep.check(True,
              f"[{theme}] `g` on the focused row opens the picker, with no drag involved",
              "picker opened")

    menu = page.evaluate("""() => {
      const m = document.querySelector('#item-menu-host [role="menu"]');
      const b = m.getBoundingClientRect();
      return {
        width: b.width, height: b.height,
        items: Array.prototype.slice.call(m.querySelectorAll('button'))
          .map((x) => ({
            text: x.textContent.trim(),
            w: x.getBoundingClientRect().width,
            h: x.getBoundingClientRect().height,
            current: x.getAttribute('aria-checked') === 'true',
          })),
      };
    }""")
    rep.check(menu["width"] > 0 and menu["height"] > 0,
              f"[{theme}] the picker is PAINTED, not merely in the DOM",
              f"{menu['width']:.0f}x{menu['height']:.0f}")
    rep.check(all(i["h"] > 0 and i["w"] > 0 for i in menu["items"]),
              f"[{theme}] every picker entry has a real painted box",
              f"{[(i['text'], round(i['h'], 1)) for i in menu['items']]}")
    labels = [i["text"] for i in menu["items"]]
    rep.check(any(x.startswith("other") for x in labels),
              f"[{theme}] the picker offers UNGROUPED as an explicit choice",
              f"items={labels}")
    rep.check(any("new group" in x for x in labels),
              f"[{theme}] and offers making a new group without leaving the row",
              f"items={labels}")
    rep.check(sum(1 for i in menu["items"] if i["current"]) == 1,
              f"[{theme}] exactly one entry is marked as the row's CURRENT group",
              f"marked={[i['text'] for i in menu['items'] if i['current']]}")

    page.evaluate("""() => {
      const m = document.querySelector('#item-menu-host [role="menu"]');
      const hit = Array.prototype.slice.call(m.querySelectorAll('button'))
        .find((b) => b.textContent.trim() === 'infra');
      hit.click();
    }""")
    page.wait_for_timeout(200)
    after = _bands(page)
    rep.check(after["rows"]["cloude_fstest"]["band"] == "g:gb",
              f"[{theme}] THE PICKER LANDS THE ROW WHERE THE DRAG DID",
              f"band={after['rows']['cloude_fstest']['band']}")
    page.close()


def measure_keyboard_route(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    assert_visible(page, rep)
    _seed(page, [{"uuid": "ga", "name": "work", "members": []}])
    page.evaluate("""() => {
      const row = document.querySelector('.session-sidebar-row');
      row.setAttribute('tabindex', '0');
      row.focus();
    }""")
    focused = page.evaluate(
        "() => document.activeElement.classList.contains('session-sidebar-row')")
    rep.check(focused, "a row can take real DOM focus, so the key route has a target",
              f"focused={focused}")
    page.keyboard.press("g")
    page.wait_for_timeout(150)
    painted = page.evaluate("""() => {
      const m = document.querySelector('#item-menu-host [role="menu"]');
      if (!m) return null;
      const b = m.getBoundingClientRect();
      return { w: b.width, h: b.height,
               focused: document.activeElement.tagName === 'BUTTON' };
    }""")
    rep.check(painted is not None and painted["w"] > 0 and painted["h"] > 0,
              "`g` opens the picker with a real painted box and NO pointer used",
              f"{painted}")
    rep.check(bool(painted and painted["focused"]),
              "and focus moves into it, so the keyboard can pick without a mouse",
              f"{painted}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    gone = page.evaluate(
        "() => !document.querySelector('#item-menu-host [role=menu]')")
    rep.check(gone, "Escape closes it again", f"closed={gone}")
    page.close()


def measure_delete_frees_rows(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    assert_visible(page, rep)
    _seed(page, [{"uuid": "ga", "name": "work",
                  "members": ["cloude_fstest", "cloude_Test"]}])
    before = _bands(page)
    n_before = len(before["rows"])
    rep.check(before["rows"]["cloude_fstest"]["band"] == "g:ga",
              "the rows start inside the group about to be deleted",
              f"band={before['rows']['cloude_fstest']['band']}")

    page.locator('.session-sidebar-group[data-group="g:ga"] .session-sidebar-group__headerrow').first.click(button="right")
    page.wait_for_selector('#item-menu-host [role="menu"]', timeout=4000)
    page.locator('#item-menu-host [role^="menuitem"]', has_text="remove").first.click()
    page.locator("#modal-confirm").click(timeout=4000)
    page.wait_for_timeout(250)

    after = _bands(page)
    rep.check(len(after["rows"]) == n_before,
              "EVERY conversation still renders after its group is deleted",
              f"rows before={n_before} after={len(after['rows'])}")
    for name in ("cloude_fstest", "cloude_Test"):
        row = after["rows"].get(name)
        rep.check(row is not None and row["height"] > 0,
                  f"{name} survives the delete with a real painted box",
                  f"{row}")
    rep.check("g:ga" not in after["bands"],
              "and the group's own section is gone",
              f"bands={sorted(after['bands'])}")
    rep.check("2 conversations moved to other" in after.get("live", ""),
              "the announcement NAMES how many moved, rather than just 'deleted'",
              f"live={after.get('live')!r}")
    page.close()


def measure_failed_write_snaps_back(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    assert_visible(page, rep)
    _seed(page, [
        {"uuid": "ga", "name": "work", "members": ["cloude_fstest"]},
        {"uuid": "gb", "name": "infra", "members": []},
    ])
    page.evaluate("() => window.__failNextGroupWrite('datastore is unavailable')")
    page.evaluate("() => document.querySelector('.session-sidebar-row[data-name=\"cloude_fstest\"]').focus()")
    page.keyboard.press("g")
    page.wait_for_selector('#item-menu-host [role="menu"]', timeout=4000)
    page.locator('#item-menu-host [role^="menuitem"], #item-menu-host [role="menuitemradio"]', has_text="infra").first.click()
    page.wait_for_timeout(300)

    after = _bands(page)
    rep.check(after["rows"]["cloude_fstest"]["band"] == "g:ga",
              "CONTROL: a FAILED move leaves the row in the group it started in",
              f"band={after['rows']['cloude_fstest']['band']}")
    rep.check("could not move" in after.get("live", ""),
              "CONTROL: and the failure is SAID, not swallowed",
              f"live={after.get('live')!r}")
    rep.check("datastore is unavailable" in after.get("live", ""),
              "CONTROL: with the reason, so it is actionable",
              f"live={after.get('live')!r}")
    page.close()


def measure_edge_symmetry_survives(browser, port: int, rep: Report) -> None:
    page = open_page(browser, port, {DENSITY_KEY: "cozy"})
    assert_viewport(page, rep)
    assert_visible(page, rep)
    _seed(page, [{"uuid": "ga", "name": "work", "members": ["cloude_fstest"]}])
    sym = page.evaluate("""() => {
      const out = [];
      for (const r of document.querySelectorAll('.session-sidebar-row')) {
        const cs = getComputedStyle(r);
        out.push({
          name: r.dataset.name,
          left: cs.borderLeftWidth, right: cs.borderRightWidth,
          leftColor: cs.borderLeftColor, rightColor: cs.borderRightColor,
          shadow: cs.boxShadow,
        });
      }
      return out;
    }""")
    for row in sym:
        rep.check(row["left"] == row["right"],
                  f"{row['name']}: left and right border WIDTH still match",
                  f"L={row['left']} R={row['right']}")
        rep.check(row["leftColor"] == row["rightColor"],
                  f"{row['name']}: left and right border COLOUR still match",
                  f"L={row['leftColor']} R={row['rightColor']}")
        rep.check("inset" not in (row["shadow"] or ""),
                  f"{row['name']}: no inset shadow rail was introduced",
                  f"shadow={row['shadow']}")
    page.close()


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"CANNOT DETERMINE: playwright is not importable under {sys.executable}")
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
                for theme in THEMES:
                    measure_drag_between_groups(browser, port, rep, theme)
                    measure_non_drag_parity(browser, port, rep, theme)
                measure_row_follows_the_finger(browser, port, rep)
                measure_drag_within_band_is_a_no_op(browser, port, rep)
                measure_keyboard_route(browser, port, rep)
                measure_delete_frees_rows(browser, port, rep)
                measure_failed_write_snaps_back(browser, port, rep)
                measure_edge_symmetry_survives(browser, port, rep)
            except Exception as exc:  # noqa: BLE001
                print("\n".join(rep.lines))
                print(f"CANNOT DETERMINE: the measurement run did not complete: "
                      f"{type(exc).__name__}: {exc}")
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
