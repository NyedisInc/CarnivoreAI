from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MENU_PAGES_TS = REPO / "web" / "src" / "lib" / "menu-page" / "menu-pages.ts"

TOLERANCE_PX = 0.5


@dataclass(frozen=True)
class Layout:

    name: str
    width: int
    height: int
    touch: bool
    header_h: float
    button_h: float


DESKTOP = Layout("desktop", 1280, 800, False, header_h=37, button_h=26)
PHONE = Layout("phone", 390, 844, True, header_h=56, button_h=44)
LAYOUTS = (DESKTOP, PHONE)
SIDE_W = 208
PHONE_VIEW_MAX_W = 700
NOT_ON_PHONE: dict[str, str] = {"warroom": "web/src/lib/warroom/phone.svelte.ts"}
THEMES = ("dracula", "carnivore-light")

TITLE_ROWS = ".oc-titlebar, .pl-titlebar, .oc-frame-title, [data-widget-head], .sbr-flyout__title, [data-frame-region='header']"


@dataclass(frozen=True)
class MenuPage:

    id: str
    container: str
    hash: str
    frame: str


def offered(page: MenuPage, layout: Layout) -> bool:
    return not (page.id in NOT_ON_PHONE and layout.width <= PHONE_VIEW_MAX_W)


class GeometryError(Exception):
    pass


_ENTRY = re.compile(
    r"\{\s*id:\s*'([^']+)',\s*containerId:\s*'([^']+)'.*?hashes:\s*\[\s*'(#[^']+)'.*?frame:\s*'([a-z]+)'\s*\}", re.S
)


def menu_pages(path: Path = MENU_PAGES_TS) -> list[MenuPage]:
    if not path.is_file():
        raise GeometryError(f"{path} is missing: no page list to measure")
    found = [MenuPage(*m.groups()) for m in _ENTRY.finditer(path.read_text())]
    if not found:
        raise GeometryError(f"{path} yielded no MENU_PAGES entry: the reader no longer matches the file")
    return found


_MEASURE_CONTROLS = """
const GROUPS = '.oc-segmented, .oc-titlebar__controls .oc-page__chips';
const measureControls = (keys, box) => {
  const controls = keys.map((key) => ({ el: key.closest(GROUPS) ?? key, key }));
  return controls.filter((c, i) => controls.findIndex((o) => o.el === c.el) === i).map(({ el, key }) => ({
    name: (key.getAttribute('aria-label') || key.textContent || '').trim().slice(0, 24), icon: el === key && key.dataset.size === 'icon', ...box(el) }));
};
"""

PAGE_PROBE = """
(containerId) => {
""" + _MEASURE_CONTROLS + """
  const box = (el) => { const r = el.getBoundingClientRect(); return { w: r.width, h: r.height }; };
  const shown = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const roots = [...(document.getElementById(containerId)?.querySelectorAll('.oc-page[data-frame]') ?? [])]
    .filter((root) => !root.parentElement.closest('.oc-page'));
  return roots.map((root) => {
    const header = root.querySelector(':scope > .oc-titlebar');
    const buttons = measureControls([...root.querySelectorAll('[data-btn-density="frame"] [data-btn]')]
      .filter((b) => shown(b) && !['auto', 'bare'].includes(b.dataset.size) && !b.closest('.oc-page__side')), box);
    const sides = [...root.querySelectorAll('.oc-page__side')].filter((s) => shown(s) && !s.hasAttribute('data-open')).map(box);
    return { frame: root.dataset.frame, pair: root.dataset.pair ?? null, header: header && shown(header) ? box(header) : null, buttons, sides };
  });
}
"""

FLYOUT_PROBE = """
(titleRows) => {
""" + _MEASURE_CONTROLS + """  const box = (el) => { const r = el.getBoundingClientRect(); return { w: r.width, h: r.height }; };
  const shown = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const host = document.querySelector('.sbr-flyout--open');
  if (!host) return null;
  const buttons = measureControls([...host.querySelectorAll('.sbr-flyout__title [data-btn], .sbr-flyout__actions [data-btn]')]
    .filter((b) => shown(b) && !['auto', 'bare'].includes(b.dataset.size)), box);
  const rows = [...(host.querySelector('.sbr-flyout__body')?.querySelectorAll(titleRows) ?? [])].filter(shown)
    .map((el) => el.className.toString().split(' ')[0] || el.tagName.toLowerCase());
  return { id: host.dataset.flyout, buttons, rows };
}
"""


@dataclass
class Findings:

    rows: set[str] = field(default_factory=set)
    pages: set[str] = field(default_factory=set)
    flyouts: set[str] = field(default_factory=set)


def _off(got: float, want: float) -> bool:
    return abs(got - want) > TOLERANCE_PX


def check_buttons(buttons: list[dict], layout: Layout) -> list[str]:
    out = set()
    for b in buttons:
        if _off(b["h"], layout.button_h):
            out.add(f"button {b['name']} {round(b['h'], 1):g} != {layout.button_h:g}")
        elif b["icon"] and _off(b["w"], b["h"]):
            out.add(f"icon {b['name']} not square")
    return sorted(out)


def check_page(page: str, roots: list[dict], layout: Layout) -> list[str]:
    if not roots:
        raise GeometryError(f"{page}: no framed page root to measure at {layout.name}")
    checks: set[str] = set()
    for root in roots:
        head = root["header"]
        if head is not None and _off(head["h"], layout.header_h):
            checks.add(f"header {round(head['h'], 1):g} != {layout.header_h:g}")
        checks.update(check_buttons(root["buttons"], layout))
        if root.get("pair") != "list":
            checks.update(f"side {round(s['w'], 1):g} != {SIDE_W}" for s in root["sides"] if _off(s["w"], SIDE_W))
    if all(root["header"] is None for root in roots):
        checks.add("no header")
    return sorted(f"{layout.name}::{page}::{c}" for c in checks)


def check_flyout(found: dict | None, flyout: str, layout: Layout) -> list[str]:
    if not found or found.get("id") != flyout:
        raise GeometryError(f"slide-out {flyout} did not open at {layout.name}")
    rows = [f"flyout {c}" for c in check_buttons(found["buttons"], layout)]
    rows += [f"flyout second title row {name}" for name in sorted(set(found["rows"]))]
    return sorted(f"{layout.name}::{flyout}::{r}" for r in rows)
