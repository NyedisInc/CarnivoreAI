from __future__ import annotations

from pathlib import Path

import pytest

from scripts.design import frame_header_controls as fhc
from scripts.design import raw_controls as rc

KNOWN_FRAME_HEADER_CONTROLS: list[str] = []


def test_scan_sees_the_tree() -> None:
    _found, pages = fhc.scan_counted()
    assert pages > 15, f"read only {pages} files that draw a <Page; the walk is broken"


def test_no_header_grew_a_raw_control() -> None:
    grown = sorted(set(fhc.rows(fhc.scan())) - set(KNOWN_FRAME_HEADER_CONTROLS))
    assert not grown, "a Page header or toolbar snippet draws a raw button / .modal-btn / .oc-btn; use Button or IconButton (web/src/lib/base):\n  " + "\n  ".join(grown)


def test_known_list_is_not_stale() -> None:
    gone = sorted(set(KNOWN_FRAME_HEADER_CONTROLS) - set(fhc.rows(fhc.scan())))
    assert not gone, "a header control moved to the base: delete its row:\n  " + "\n  ".join(gone)
    assert len(set(KNOWN_FRAME_HEADER_CONTROLS)) == len(KNOWN_FRAME_HEADER_CONTROLS)


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "web" / "src"
    for rel, text in files.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)
    return src


def _scan(tmp_path: Path, files: dict[str, str]) -> dict[str, list[tuple[int, str]]]:
    return fhc.scan(_tree(tmp_path, files), tmp_path)


def test_negative_control_planted_raw_header_controls_go_red(tmp_path: Path) -> None:
    found = _scan(tmp_path, {
        "A.svelte": (
            "<script>import Acts from './Acts.svelte'; import Button from './Button.svelte';</script>\n"
            "{#snippet pageActions()}\n  <button class=\"x\">a</button>\n  <Acts />\n  <Button>fine</Button>\n{/snippet}\n"
            "<Page title=\"a\" actions={open ? undefined : pageActions}>\n"
            "  {#snippet bar()}<a class=\"oc-btn oc-btn--sm\" href=\"/\">b</a>{/snippet}\n"
            "  <button>body buttons are not the header</button>\n</Page>\n"
        ),
        "Acts.svelte": '<button type="button" class="modal-btn modal-btn-secondary">r</button><button data-btn="row">ok</button>',
    })
    assert {rel: [line for line, _key in items] for rel, items in found.items()} == {"web/src/A.svelte": [3, 8], "web/src/Acts.svelte": [1]}
    assert fhc.rows(found)[0].startswith("web/src/A.svelte::<")
    assert set(fhc.rows(found)) - set(KNOWN_FRAME_HEADER_CONTROLS)


def test_negative_control_base_buttons_and_other_snippets_stay_green(tmp_path: Path) -> None:
    assert _scan(tmp_path, {"A.svelte": (
        '{#snippet actions()}<Button variant="confirm">go</Button><IconButton label="x" icon="close" /><button data-btn="row">r</button>'
        '<button class="x" data-base-exempt="xterm toolbar">e</button>{/snippet}\n'
        "{#snippet side()}<button class=\"modal-btn\">not a header snippet</button>{/snippet}\n<Page title=\"a\" />"
    )}) == {}


def test_negative_control_the_find_sub_and_search_snippets_are_scanned(tmp_path: Path) -> None:
    found = _scan(tmp_path, {"A.svelte": (
        '<Page title="a">{#snippet find()}<button>f</button>{/snippet}\n{#snippet sub()}<a class="modal-btn" href="/">s</a>{/snippet}\n'
        '{#snippet search()}<button>q</button>{/snippet}</Page>'
    )})
    assert len(found["web/src/A.svelte"]) == 3


def test_negative_control_manager_frame_header_snippets_are_scanned(tmp_path: Path) -> None:
    found = _scan(tmp_path, {"M.svelte": (
        "{#snippet paneStrip(item)}<button class=\"oc-btn\">s</button>{/snippet}\n"
        "<ManagerFrame title=\"m\" detailBar={paneStrip}>\n"
        "  {#snippet actions()}<button>a</button>{/snippet}\n"
        "  {#snippet toolbar()}<button class=\"oc-btn\">t</button><Button>fine</Button>{/snippet}\n"
        "  {#snippet body()}<button>body buttons are not the header</button>{/snippet}\n</ManagerFrame>\n"
    )})
    assert [line for line, _key in found["web/src/M.svelte"]] == [1, 3, 4]


def test_a_repeated_control_in_one_file_is_a_row_each() -> None:
    assert fhc.rows({"a.svelte": [(1, "<button>"), (4, "<button>")]}) == ["a.svelte::<button>", "a.svelte::<button>#2"]


def test_negative_control_a_missing_or_page_less_tree_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(rc.ScanError):
        fhc.scan(tmp_path / "nope", tmp_path)
    src = _tree(tmp_path, {"A.svelte": "<div><button>x</button></div>"})
    with pytest.raises(rc.ScanError):
        fhc.scan(src, tmp_path)
