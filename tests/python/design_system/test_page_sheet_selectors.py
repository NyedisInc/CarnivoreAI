from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.design import raw_values, reach_ins
from scripts.design.reach_ins import split_top_level, style_preludes
from tests.python.design_system._sources import REPO, strip_comments

SCAN_ROOTS = (REPO / "web" / "src" / "lib", REPO / "web" / "src" / "plugins", REPO / "client" / "css")
EXCLUDED_DIRS = (REPO / "web" / "src" / "lib" / "base",)
MIN_SHEETS = 100

KNOWN: frozenset[str] = frozenset()

BARE_ELEMENTS = frozenset(
    "a button code dialog em h1 h2 h3 h4 h5 h6 hr img input kbd label li ol p pre select small strong summary svg "
    "table td textarea th ul".split()
)
SHARED_LEAD = re.compile(r"^(?:\[data-btn|\[data-field|\.oc-btn\b|\.modal-btn|\.oc-field\b)")
LEADING_TYPE = re.compile(r"^([a-z][a-z0-9]*)(?![\w-])(.*)$", re.S)
QUALIFIER = re.compile(r"^[.#\[]")


def sheets() -> list[Path]:
    found: list[Path] = []
    for root in SCAN_ROOTS:
        found += [p for p in root.rglob("*.css") if not any(d in p.parents for d in EXCLUDED_DIRS)]
    return sorted(found)


def leak_of(selector: str) -> str | None:
    if SHARED_LEAD.match(selector):
        return "shared base " + re.split(r"[\s>+~:]", selector, maxsplit=1)[0]
    match = LEADING_TYPE.match(selector)
    if match and match.group(1) in BARE_ELEMENTS and not QUALIFIER.match(match.group(2)):
        return "bare element " + match.group(1)
    return None


def leaks_in(css: str) -> list[str]:
    found: list[str] = []
    for prelude in style_preludes(css):
        for selector in split_top_level(prelude, ","):
            if leak_of(selector):
                found.append(selector)
    return found


def all_leaks() -> set[str]:
    found: set[str] = set()
    for path in sheets():
        rel = path.relative_to(REPO).as_posix()
        found |= {f"{rel}:{s}" for s in leaks_in(strip_comments(path.read_text()))}
    return found


def test_scan_finds_its_sheets() -> None:
    empty = [str(r) for r in SCAN_ROOTS if not any(r.rglob("*.css"))]
    assert not empty, f"scan roots with no stylesheet (moved or missing): {empty}"
    assert len(sheets()) >= MIN_SHEETS, f"only {len(sheets())} sheets under {[str(r) for r in SCAN_ROOTS]}"


def test_no_page_sheet_selector_reaches_app_wide() -> None:
    new = sorted(all_leaks() - KNOWN)
    assert not new, "page sheet selectors that reach app-wide (scope under a page root, or fix the base):\n" + "\n".join(new)


def test_known_only_falls() -> None:
    stale = sorted(KNOWN - all_leaks())
    assert not stale, f"KNOWN entries no longer leak, remove them: {stale}"


@pytest.mark.parametrize(
    "css",
    ["code { color: red; }", "@layer components { [data-btn][data-filled='true'] { color: red; } }",
     "@media (max-width: 1px) { .modal-btn.x { color: red; } }", ".ok, h2 { margin: 0; }"],
)
def test_planted_violation_is_caught(css: str) -> None:
    assert leaks_in(css)


@pytest.mark.parametrize(
    "css",
    [".rs-root code { color: red; }", "button.d-ev__btn:hover { color: red; }", ".a :is(h2, h3) { margin: 0; }",
     "body.x { margin: 0; }", "@keyframes k { from { opacity: 0; } to { opacity: 1; } }"],
)
def test_scoped_rules_pass(css: str) -> None:
    assert not leaks_in(css)


def test_missing_subject_files_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(__import__(__name__, fromlist=["x"]), "SCAN_ROOTS", (tmp_path / "gone",))
    with pytest.raises(AssertionError):
        test_scan_finds_its_sheets()


REACH_FLOOR = 100


def test_reach_ins_only_fall() -> None:
    found = reach_ins.scan()
    assert len(found) >= REACH_FLOOR, f"only {len(found)} files with a reach-in: a scan root moved or the scan read nothing"
    grown, stale = raw_values.compare(found, reach_ins.load_baseline(), reach_ins.KINDS)
    assert not grown, "new reach-ins into a shared base control (use a base variant or a token, never restyle it):\n" + "\n".join(grown)
    assert not stale, "reach-ins removed; lower the baseline with python3 -m scripts.design.reach_ins --write:\n" + "\n".join(stale)


@pytest.mark.parametrize(
    ("css", "kind"),
    [(".wp-screen .wp-add > [data-btn] { border: 0; }", "hook"), (".x .oc-pick__input { color: x; }", "hook"),
     (".x :global(.modal-btn-danger) { color: x; }", "hook"), (".x [data-field='search'] { color: x; }", "hook"),
     (".x :global(.oc-row) { color: x; }", "global"), (".x { --_btn-bg: var(--a); }", "private-write"),
     (".x { --_pick-h: 2px; }", "private-write"), (".x { color: var(--a) !important; }", "important"),
     ("@media (max-width: 1px) { .x { gap: 0 ! important; } }", "important")],
)
def test_negative_control_each_reach_in_kind_is_counted(css: str, kind: str) -> None:
    assert reach_ins.count_css(css) == {**dict.fromkeys(reach_ins.KINDS, 0), kind: 1}


@pytest.mark.parametrize(
    "css",
    [".x .oc-button-ish { color: x; }", ".x .modal-btnx { color: x; }", ".x { color: var(--_btn-bg); --_own-bg: 1px; }",
     ".x [data-btnish] { color: x; }", ":global(.app-root) .x { color: x; }"],
)
def test_reach_in_lookalikes_are_not_counted(css: str) -> None:
    assert reach_ins.count_css(css) == dict.fromkeys(reach_ins.KINDS, 0)


def test_negative_control_a_planted_reach_in_goes_red_and_the_owners_are_not_read(tmp_path: Path) -> None:
    web = tmp_path / "web" / "src"
    (web / "lib" / "base").mkdir(parents=True)
    (web / "lib" / "base" / "elements.css").write_text(":where([data-btn]) { --_btn-bg: x; }\n")
    (web / "Page.svelte").write_text("<div></div>\n<style>.p :global(.oc-btn) { border: 0 !important; }</style>\n")
    roots = ((web, frozenset({".css", ".svelte"})),)
    found = reach_ins.scan(roots, tmp_path)
    assert found == {"web/src/Page.svelte": {"hook": 1, "global": 1, "important": 1}}
    grown, _ = raw_values.compare(found, {}, reach_ins.KINDS)
    assert grown == ["web/src/Page.svelte hook: 1 > 0", "web/src/Page.svelte global: 1 > 0", "web/src/Page.svelte important: 1 > 0"]
    with pytest.raises(FileNotFoundError):
        reach_ins.scan(((tmp_path / "gone", frozenset({".css"})),), tmp_path)


def test_the_reach_in_scan_covers_every_tree() -> None:
    found = reach_ins.load_baseline()
    for prefix in ("web/src/", "src/plugins/", "client/css/"):
        assert any(rel.startswith(prefix) for rel in found), prefix
    assert not any(reach_ins.is_owner(rel) for rel in found)


def test_plugin_sheets_are_held_by_the_reach_in_ratchet(tmp_path: Path) -> None:
    plugin = tmp_path / "web" / "src" / "plugins" / "zz"
    plugin.mkdir(parents=True)
    (plugin / "look.css").write_text(".zz-head .oc-btn { --_btn-bg: x; }\n")
    found = reach_ins.scan(((tmp_path / "web" / "src", frozenset({".css"})),), tmp_path)
    assert found == {"web/src/plugins/zz/look.css": {"hook": 1, "private-write": 1}}
    held = {rel.split("/")[3] for rel in reach_ins.load_baseline() if rel.startswith("web/src/plugins/")}
    assert len(held) >= 4, held
