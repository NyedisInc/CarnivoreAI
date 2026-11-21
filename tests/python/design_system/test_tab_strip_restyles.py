from __future__ import annotations

import re
from pathlib import Path

from scripts.design.frame_regions import is_allowed as _frame_allowed
from tests.python.design_system._sources import REPO, css_of, split_selectors
from tests.python.design_system.test_frame_tab_height import tabs_strip_classes

OWN = "web/src/opscenter/ui/tabs.css"
STRIP_CLASSES = frozenset({"oc-ptabs", "oc-ptabs__list", "oc-ptab"})
SIZING = re.compile(r"^(?:height|min-height|max-height|padding(?:-[a-z]+)*|flex(?:-grow|-shrink|-basis)?|gap|row-gap|column-gap)$")
_CLASS = re.compile(r"\.([A-Za-z_][\w-]*)")
_COMBINATOR = re.compile(r"\s*[>+~]\s*|\s+")

KNOWN_TAB_STRIP_RESTYLES: list[str] = [
    "web/src/admin/admin.css::.admin-panel .oc-ptab",
    "web/src/lib/plugins-page/plugin-pane.css::.plp .plp-tabs",
    "web/src/lib/plugins-page/plugin-pane.css::.plp .plp-tabs .oc-ptab",
    "web/src/lib/plugins-page/plugin-pane.css::.wik .plp .plp-tabs .oc-ptab",
    "web/src/lib/publish-page/page.css::.d-tabs .oc-ptab",
    "web/src/lib/publish-page/page.css::.d-tabs .oc-ptabs",
    "web/src/lib/session-control/control-center.css::.scc-tabs",
    "web/src/lib/settings-page/settings-page.css::.settings-page .st-phonetabs .oc-ptabs",
    "web/src/lib/settings-page/settings-page.css::.settings-page .st-tabs",
    "web/src/opscenter/cells/developer/Cell.svelte::.oc-dv :global(.oc-ptab)",
]


def rules(css: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    stack: list[tuple[str, list[str]]] = []
    start = 0
    for i, ch in enumerate(css):
        if ch == "{":
            stack.append((css[start:i].strip(), []))
            start = i + 1
        elif ch == "}":
            if stack:
                head, own = stack.pop()
                own.append(css[start:i])
                if head and not head.startswith("@"):
                    out.append((head, "".join(own)))
            start = i + 1
        elif ch == ";" and stack:
            stack[-1][1].append(css[start:i + 1])
            start = i + 1
    return out


def sizes_strip(body: str) -> bool:
    return any(SIZING.match(decl.split(":", 1)[0].strip()) for decl in body.split(";") if ":" in decl)


def names_strip(selector: str, classes: frozenset[str]) -> bool:
    plain = selector.replace(":global(", " ").replace(")", " ").strip()
    subject = _COMBINATOR.split(plain)[-1] if plain else ""
    return bool(set(_CLASS.findall(subject)) & classes)


def strip_classes(root: Path = REPO) -> frozenset[str]:
    found = set(STRIP_CLASSES)
    for path in (root / "web" / "src").rglob("*.svelte"):
        found |= tabs_strip_classes(path.read_text())
    return frozenset(found)


def scan(root: Path = REPO) -> tuple[list[str], int]:
    classes = strip_classes(root)
    out: list[str] = []
    read = 0
    for path in sorted(p for suffix in ("*.css", "*.svelte") for p in (root / "web" / "src").rglob(suffix)):
        rel = path.relative_to(root).as_posix()
        css = css_of(path)
        if not css:
            continue
        read += 1
        if rel == OWN or (_frame_allowed(rel) and rel.startswith("web/src/style-guide/")):
            continue
        seen: dict[str, int] = {}
        for head, body in rules(css):
            if not sizes_strip(body):
                continue
            for sel in split_selectors(head):
                if names_strip(sel, classes):
                    key = " ".join(sel.split())
                    seen[key] = seen.get(key, 0) + 1
                    out.append(f"{rel}::{key}" + (f"#{seen[key]}" if seen[key] > 1 else ""))
    return sorted(out), read


def test_scan_sees_the_tree() -> None:
    _rows, read = scan()
    assert read > 200, f"read only {read} stylesheets; the walk is broken"


def test_no_page_sizes_the_shared_tab_strip() -> None:
    grown = sorted(set(scan()[0]) - set(KNOWN_TAB_STRIP_RESTYLES))
    assert not grown, "a page sizes the shared tab strip; take the strip's own size or add a variant to tabs.css:\n  " + "\n  ".join(grown)


def test_known_list_is_not_stale() -> None:
    gone = sorted(set(KNOWN_TAB_STRIP_RESTYLES) - set(scan()[0]))
    assert not gone, "a strip restyle was removed: delete its row from KNOWN_TAB_STRIP_RESTYLES:\n  " + "\n  ".join(gone)
    assert len(set(KNOWN_TAB_STRIP_RESTYLES)) == len(KNOWN_TAB_STRIP_RESTYLES)


def test_negative_control_planted_strip_restyles_go_red(tmp_path: Path) -> None:
    lib = tmp_path / "web" / "src" / "lib" / "x"
    lib.mkdir(parents=True)
    (lib / "X.svelte").write_text('<Tabs tabs={t} class="x-tabs" />\n<style>:global(.x .x-tabs) { height: 30px }</style>')
    (lib / "x.css").write_text(
        "@layer pages { .x .oc-ptab { min-height: 32px } .x .oc-ptab:hover { color: red } .oc-ptab .x-mark { padding: 0 } }"
    )
    rows, read = scan(tmp_path)
    assert read == 2 and rows == ["web/src/lib/x/X.svelte:::global(.x .x-tabs)", "web/src/lib/x/x.css::.x .oc-ptab"], rows
