from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WEB_SRC = REPO / "web" / "src"
FRAME = "web/src/opscenter/ui/Page.svelte"
_BODY = re.compile(r"(?<![\w-])oc-page__body(?![\w-])")
_ROWS = re.compile(r"(?<![\w-])oc-page__(?:tabs|bar)(?![\w-])")
_STYLE = re.compile(r"<style[^>]*>.*?</style>", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)

KNOWN_NESTED_BODIES: list[str] = []


KNOWN_OWN_ROWS: list[str] = []
SPECIMENS = "web/src/style-guide/"


def nested_body_files(root: Path = REPO, pattern: re.Pattern[str] = _BODY) -> tuple[list[str], int]:
    found: list[str] = []
    read = 0
    for path in sorted((root / "web" / "src").rglob("*.svelte")):
        read += 1
        rel = path.relative_to(root).as_posix()
        if rel == FRAME:
            continue
        markup = _COMMENT.sub("", _STYLE.sub("", path.read_text()))
        if pattern.search(markup):
            found.append(rel)
    return found, read


def test_scan_sees_the_tree() -> None:
    _found, read = nested_body_files()
    assert read > 300, f"read only {read} Svelte files; the walk is broken"


def test_no_page_grew_a_nested_body() -> None:
    found, _ = nested_body_files()
    grown = sorted(set(found) - set(KNOWN_NESTED_BODIES))
    assert not grown, "a page draws its own oc-page__body inside the frame's; use a plain layout class:\n  " + "\n  ".join(grown)


def test_known_list_is_not_stale() -> None:
    found, _ = nested_body_files()
    gone = sorted(set(KNOWN_NESTED_BODIES) - set(found))
    assert not gone, "a nested body was removed: delete its row from KNOWN_NESTED_BODIES:\n  " + "\n  ".join(gone)
    assert len(set(KNOWN_NESTED_BODIES)) == len(KNOWN_NESTED_BODIES)


def test_negative_control_a_planted_nested_body_goes_red(tmp_path: Path) -> None:
    page = tmp_path / "web" / "src" / "lib" / "x" / "X.svelte"
    page.parent.mkdir(parents=True)
    page.write_text('<Page frame="column"><div class="oc-page__body x-body">a</div></Page>\n<style>.oc-page__body { a: b }</style>')
    ok = tmp_path / "web" / "src" / "lib" / "x" / "Ok.svelte"
    ok.write_text('<div class="oc-page__body--reading y"></div><!-- oc-page__body --><style>.oc-page__body { a: b }</style>')
    found, read = nested_body_files(tmp_path)
    assert (found, read) == (["web/src/lib/x/X.svelte"], 2)


def test_no_page_draws_its_own_tab_or_tool_row() -> None:
    found = [rel for rel in nested_body_files(pattern=_ROWS)[0] if not rel.startswith(SPECIMENS)]
    grown = sorted(set(found) - set(KNOWN_OWN_ROWS))
    assert not grown, "a page draws the frame's tab or tool row itself; hand it to Page's tabs or bar snippet:\n  " + "\n  ".join(grown)
    gone = sorted(set(KNOWN_OWN_ROWS) - set(found))
    assert not gone, "a page stopped drawing its own row: delete it from KNOWN_OWN_ROWS:\n  " + "\n  ".join(gone)


def test_negative_control_a_planted_tool_row_goes_red(tmp_path: Path) -> None:
    page = tmp_path / "web" / "src" / "lib" / "x" / "X.svelte"
    page.parent.mkdir(parents=True)
    page.write_text('<div class="oc-page__bar x-bar"><input /></div>\n<style>.oc-page__tabs { a: b }</style>')
    ok = tmp_path / "web" / "src" / "lib" / "x" / "Ok.svelte"
    ok.write_text('<div class="oc-page__bar--picker y"></div><!-- oc-page__tabs -->')
    found, read = nested_body_files(tmp_path, _ROWS)
    assert (found, read) == (["web/src/lib/x/X.svelte"], 2)
