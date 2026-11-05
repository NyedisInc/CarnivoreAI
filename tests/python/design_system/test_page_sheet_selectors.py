from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.python.design_system._sources import REPO, strip_comments

SCAN_ROOTS = (REPO / "web" / "src" / "lib", REPO / "web" / "src" / "cplugs", REPO / "client" / "css")
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


def split_top_level(text: str, sep: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in text:
        depth += (ch in "([") - (ch in ")]")
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


def style_preludes(css: str) -> list[str]:
    out: list[str] = []
    stack: list[bool] = []
    start = 0
    for i, ch in enumerate(css):
        if ch == "{":
            prelude = css[start:i].strip()
            is_rule = not prelude.startswith("@") and not any(stack)
            if is_rule and prelude:
                out.append(prelude)
            stack.append(not prelude.startswith("@"))
            start = i + 1
        elif ch == "}":
            if stack:
                stack.pop()
            start = i + 1
        elif ch == ";" and not any(stack):
            start = i + 1
    return out


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
