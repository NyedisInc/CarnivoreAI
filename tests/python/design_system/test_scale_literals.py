from __future__ import annotations

import ast
import json
import operator
import re
from pathlib import Path

from scripts.design.raw_values import css_text, is_exempt, strip_vars
from tests.python.design_system.test_theme_contract import PRE_MIGRATION_RADII

REPO = Path(__file__).resolve().parents[3]
TOKENS = REPO / "web" / "src" / "opscenter" / "tokens.css"
STYLES = REPO / "client" / "css" / "styles.css"
THEMES = REPO / "client" / "css" / "themes"
ROOTS = (REPO / "web" / "src", REPO / "client" / "css")
SHAPES = frozenset({"--oc-radius-round", "--oc-radius-circle", "--oc-radius-frame"})
Z_GLOBAL_FLOOR = 10

_DECL = re.compile(r"(?<![\w-])([a-z-]+)\s*:\s*([^;{}]+)")
_RADIUS_PROP = re.compile(r"^border(?:-(?:top|bottom|start|end)-(?:left|right|start|end))?-radius$")
_NONZERO_LENGTH = re.compile(r"(?<![\w.#-])(?!0+(?:\.0+)?(?:px|%|r?em|cqw)?(?![\w.]))\d*\.?\d+(?:px|%|r?em|cqw|vh|vw)?(?![\w.])")
_Z_NUMBER = re.compile(r"^\s*(-?\d+)\s*(?:!important)?\s*$")
_RUNG = re.compile(r"^\s*(--oc-radius[a-z-]*)\s*:\s*([^;]+);", re.M)
_LEGACY = re.compile(r"(--radius-(?:sm|md|lg))\s*:\s*([^;]+);")
_VAR = re.compile(r"var\((--[a-z0-9-]+)(?:,\s*([^()]*(?:\([^()]*\))?[^()]*))?\)")
_PX = re.compile(r"(-?\d*\.?\d+)px")

RADIUS_LITERALS_KNOWN: dict[str, int] = {
    "client/css/styles.css": 1,
    "web/src/plugins/taskmanager/chat/ChatWidget.svelte": 1,
    "web/src/plugins/taskmanager/swarm/SwarmLedger.svelte": 4,
    "web/src/plugins/taskmanager/swarm/SwarmOrg.svelte": 4,
    "web/src/plugins/taskmanager/swarm/SwarmPanel.svelte": 3,
    "web/src/plugins/taskmanager/swarm/characters/characters.css": 7,
    "web/src/lib/catalog/AccountPanel.svelte": 1,
    "web/src/lib/catalog/CardImageRow.svelte": 1,
    "web/src/lib/catalog/CatalogCard.svelte": 1,
    "web/src/lib/catalog/CatalogDetail.svelte": 1,
    "web/src/lib/catalog/CatalogRows.svelte": 1,
    "web/src/lib/catalog/CatalogScreen.svelte": 1,
    "web/src/lib/catalog/CompatBadges.svelte": 1,
    "web/src/lib/catalog/ConfirmSheet.svelte": 1,
    "web/src/lib/catalog/ConsentInstructions.svelte": 1,
    "web/src/lib/catalog/ConsentScripts.svelte": 1,
    "web/src/lib/catalog/ContentsBlock.svelte": 1,
    "web/src/lib/catalog/GradeBlock.svelte": 2,
    "web/src/lib/catalog/InstallChoices.svelte": 1,
    "web/src/lib/catalog/InstallPreview.svelte": 4,
    "web/src/lib/catalog/InstallSheet.svelte": 3,
    "web/src/lib/catalog/ItemNoteForm.svelte": 2,
    "web/src/lib/catalog/ItemNotePopup.svelte": 1,
    "web/src/lib/catalog/KindMark.svelte": 1,
    "web/src/lib/catalog/LoadoutMembers.svelte": 2,
    "web/src/lib/catalog/ModFacts.svelte": 1,
    "web/src/lib/catalog/OneShotPicker.svelte": 2,
    "web/src/lib/catalog/PluginFacts.svelte": 3,
    "web/src/lib/catalog/RatingControl.svelte": 2,
    "web/src/lib/catalog/RatingHistogram.svelte": 1,
    "web/src/lib/catalog/ReviewBlock.svelte": 2,
    "web/src/lib/catalog/TrustBlock.svelte": 3,
    "web/src/lib/catalog/TrySheet.svelte": 1,
    "web/src/lib/catalog/UpdateDiffView.svelte": 1,
    "web/src/lib/catalog/WarezTools.svelte": 2,
    "web/src/lib/catalog/catalog-phone-bar.css": 1,
    "web/src/lib/catalog/warez-card.css": 2,
    "web/src/lib/drawer-tabs/DrawerMenu.svelte": 1,
    "web/src/lib/ledger/LedgerRowSwatch.svelte": 1,
    "web/src/lib/mini-rail/MiniRailUsage.svelte": 1,
    "web/src/lib/pack-machines/PackMeter.svelte": 2,
    "web/src/lib/pack-machines/pack-machines.css": 2,
    "web/src/lib/pack-machines/pack-work.css": 2,
    "web/src/lib/pack-roster/roster.css": 15,
    "web/src/lib/publish-page/wizard.css": 1,
    "web/src/lib/skill-page/skill-page.css": 3,
    "web/src/lib/skills-page/skills-page.css": 1,
    "web/src/lib/swarm-board/views/calendar/BoardKey.svelte": 1,
    "web/src/lib/swarm-board/views/list/CardDetail.svelte": 2,
    "web/src/lib/swarm-board/views/swimlanes/LaneCard.svelte": 4,
    "web/src/lib/swarm-board/views/swimlanes/SwimLane.svelte": 1,
    "web/src/lib/swarm-board/views/timeline/TimelineGroup.svelte": 2,
    "web/src/lib/themes-page/ThemePreview.svelte": 1,
    "web/src/plugins/taskmanager/mk2/mk2-design.css": 2,
    "web/src/opscenter/ui/tabs.css": 1,
}
Z_LITERALS_KNOWN: dict[str, int] = {
    "web/src/lib/catalog/ItemNotePopup.svelte": 1,
    "web/src/lib/huddle-agent/AgentDrawer.svelte": 2,
    "web/src/lib/ledger/ColorSwatches.svelte": 1,
    "web/src/lib/pack-machines/relay-consent.css": 1,
    "web/src/lib/pack-op-toast/pack-op-toast.css": 1,
    "web/src/lib/pack-roster/roster.css": 6,
    "web/src/lib/sessions-page/pivot.css": 1,
}


class ScaleReadError(Exception):
    pass


def scan_literals(roots: tuple[Path, ...] = ROOTS, base: Path = REPO) -> tuple[dict[str, int], dict[str, int]]:
    radius: dict[str, int] = {}
    z: dict[str, int] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "node_modules" in path.parts:
                continue
            rel = path.relative_to(base).as_posix()
            if is_exempt(rel):
                continue
            r = n = 0
            for prop, value in _DECL.findall(css_text(path)):
                prop = prop.lower()
                if _RADIUS_PROP.match(prop) and _NONZERO_LENGTH.search(strip_vars(value)):
                    r += 1
                elif prop == "z-index" and (m := _Z_NUMBER.match(value)) and int(m.group(1)) >= Z_GLOBAL_FLOOR:
                    n += 1
            if r:
                radius[rel] = r
            if n:
                z[rel] = n
    return radius, z


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _arith(expr: str) -> float:
    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        raise ScaleReadError(f"not arithmetic: {expr!r}")
    try:
        return walk(ast.parse(expr.strip(), mode="eval").body)
    except SyntaxError as exc:
        raise ScaleReadError(f"not arithmetic: {expr!r}") from exc


def _px(value: str, env: dict[str, str], depth: int = 0) -> float:
    if depth > 12:
        raise ScaleReadError(f"loops at {value}")
    v = value.strip()
    while (m := _VAR.search(v)):
        name, fallback = m.group(1), m.group(2)
        raw = env.get(name, fallback)
        if raw is None:
            raise ScaleReadError(f"no value for {name} in {value}")
        v = v[: m.start()] + f"{_px(raw, env, depth + 1)}px" + v[m.end():]
    v = _PX.sub(lambda m: m.group(1), v).replace("calc", "")
    if (c := re.fullmatch(r"clamp\(([^,]+),([^,]+),([^,]+)\)", v.replace(" ", ""))):
        lo, mid, hi = (_arith(x) for x in c.groups())
        return min(max(mid, lo), hi)
    return _arith(v)


PRE_SCALE_WEB = {"--oc-radius-xs": 1.0, "--oc-radius-control": 2.0, "--oc-radius-tight": 3.0, "--oc-radius-sm": 4.0,
                 "--oc-radius": 6.0, "--oc-radius-lg": 8.0, "--oc-radius-panel": 4.0}
PRE_SCALE_LEGACY_DEFAULT = (3.0, 4.0, 8.0)


def theme_vars(theme: str) -> dict[str, str]:
    return dict(json.loads((THEMES / theme / "theme.json").read_text(encoding="utf-8"))["cssVars"])


def corners(theme_env: dict[str, str]) -> dict[str, float]:
    env = dict(theme_env)
    rungs = dict(_RUNG.findall(TOKENS.read_text(encoding="utf-8")))
    env.update(rungs)
    legacy = dict(_LEGACY.findall(STYLES.read_text(encoding="utf-8")))
    return {name: _px(raw, env) for name, raw in {**rungs, **legacy}.items() if name not in SHAPES}


def _drift(found: dict[str, int], known: dict[str, int]) -> tuple[list[str], list[str]]:
    grown = [f"{f}: {found.get(f, 0)} > {known.get(f, 0)}" for f in sorted(set(found) | set(known)) if found.get(f, 0) > known.get(f, 0)]
    stale = [f"{f}: {found.get(f, 0)} < {known[f]}" for f in sorted(known) if found.get(f, 0) < known[f]]
    return grown, stale


FOUND_RADIUS, FOUND_Z = scan_literals()


def test_two_themes_with_different_corners_move_every_rung() -> None:
    a = corners({"--radius-control": "2px", "--radius-panel": "2px"})
    b = corners({"--radius-control": "3px", "--radius-panel": "4px"})
    assert len(a) >= 10, f"read only {sorted(a)}; the rung reader is broken"
    still = sorted(k for k in a if a[k] == b[k])
    assert not still, f"corners a theme cannot move (same under 2/2 and 3/4): {still}"


def test_every_bundled_theme_keeps_its_pre_scale_corners() -> None:
    themes = sorted(p.parent.name for p in THEMES.glob("*/theme.json"))
    assert len(themes) >= 12, f"read only {themes}; the theme reader is broken"
    drift = {}
    for theme in themes:
        c = corners(theme_vars(theme))
        legacy = tuple(float(x.removesuffix("px")) for x in PRE_MIGRATION_RADII.get(theme, ())) or PRE_SCALE_LEGACY_DEFAULT
        want = {**PRE_SCALE_WEB, **dict(zip(("--radius-sm", "--radius-md", "--radius-lg"), legacy))}
        got = {k: c[k] for k in want}
        if got != want:
            drift[theme] = {k: (want[k], got[k]) for k in want if got[k] != want[k]}
    assert not drift, f"corners moved under bundled themes (token: (before, now)): {drift}"


def test_no_file_grew_a_corner_or_layer_literal() -> None:
    grown = _drift(FOUND_RADIUS, RADIUS_LITERALS_KNOWN)[0] + _drift(FOUND_Z, Z_LITERALS_KNOWN)[0]
    assert not grown, ("a literal corner or layer: use --oc-radius-* or --oc-z-* (web/src/opscenter/tokens.css):\n  "
                       + "\n  ".join(grown))


def test_known_lists_are_not_stale() -> None:
    stale = _drift(FOUND_RADIUS, RADIUS_LITERALS_KNOWN)[1] + _drift(FOUND_Z, Z_LITERALS_KNOWN)[1]
    assert not stale, "a count fell: lower it in this file:\n  " + "\n  ".join(stale)


def test_negative_control_a_planted_literal_goes_red(tmp_path: Path) -> None:
    (tmp_path / "Planted.svelte").write_text(
        "<div></div>\n<style>.x { border-radius: 5px; z-index: 40 } .y { border-radius: var(--oc-radius-sm, 4px) 0;"
        " z-index: 3 } .z { border-radius: 0 }</style>\n")
    radius, z = scan_literals((tmp_path,), tmp_path)
    assert (radius, z) == ({"Planted.svelte": 1}, {"Planted.svelte": 1})
    assert _drift(radius, {})[0] == ["Planted.svelte: 1 > 0"]


def test_negative_control_an_unmoved_rung_is_caught() -> None:
    env = {"--radius-control": "3px"}
    assert _px("clamp(0px, var(--radius-control, 2px), 4px)", env) == 3
    assert _px("clamp(0px, var(--radius-control, 2px), 4px)", {}) == 2
    try:
        _px("var(--nope)", {})
    except ScaleReadError:
        return
    raise AssertionError("an unresolvable rung read as a number")
