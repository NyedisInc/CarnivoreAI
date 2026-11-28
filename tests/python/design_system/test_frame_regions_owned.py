from __future__ import annotations

from pathlib import Path

import pytest

from scripts.design import frame_regions as fr

KNOWN_FRAME_RESTYLES: list[str] = [
]


def test_scan_sees_the_tree() -> None:
    _found, files_read = fr.scan_counted()
    assert files_read > 300, f"read only {files_read} stylesheets; the walk is broken"


def test_no_page_grew_a_frame_restyle() -> None:
    now = set(fr.rows(fr.scan()))
    grown = sorted(now - set(KNOWN_FRAME_RESTYLES))
    assert not grown, "a page restyles a frame region; add the need to the frame (opscenter/page.css), do not style it locally:\n  " + "\n  ".join(grown)


def test_known_list_is_not_stale() -> None:
    gone = sorted(set(KNOWN_FRAME_RESTYLES) - set(fr.rows(fr.scan())))
    assert not gone, "a restyle was removed: delete its row from KNOWN_FRAME_RESTYLES:\n  " + "\n  ".join(gone)
    assert len(set(KNOWN_FRAME_RESTYLES)) == len(KNOWN_FRAME_RESTYLES)


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


def test_negative_control_a_planted_page_rule_goes_red(tmp_path: Path) -> None:
    repo = _tree(tmp_path, {
        "web/src/lib/x/x.css": "@layer pages { .x .oc-page__bar { height: 50px; } .ok { color: red } }\n@media (x) { .y, .oc-titlebar--search { a: b } }\n[data-frame='nav'] > .z { a: b }",
        "web/src/lib/x/Y.svelte": "<div/>\n<style>\n.oc-page--away .q { a: b }\n:global(.oc-page__detail-head) { a: b }\n</style>",
    })
    found = fr.scan(repo)
    assert fr.rows(found) == [
        "web/src/lib/x/Y.svelte::.oc-page--away .q", "web/src/lib/x/Y.svelte:::global(.oc-page__detail-head)",
        "web/src/lib/x/x.css::.oc-titlebar--search", "web/src/lib/x/x.css::.x .oc-page__bar", "web/src/lib/x/x.css::[data-frame='nav'] > .z",
    ]
    assert set(fr.rows(found)) - set(KNOWN_FRAME_RESTYLES), "planted rows must read as growth"


def test_negative_control_a_pair_marker_selector_goes_red(tmp_path: Path) -> None:
    repo = _tree(tmp_path, {"web/src/lib/x/x.css": ".x[data-pair='list'] > .y { a: b } .ok { a: b } .z[data-pairing] { a: b }"})
    assert fr.rows(fr.scan(repo)) == ["web/src/lib/x/x.css::.x[data-pair='list'] > .y"]


def test_negative_control_the_frame_own_files_and_the_bare_root_are_clean(tmp_path: Path) -> None:
    repo = _tree(tmp_path, {
        "web/src/opscenter/page.css": ".oc-page__bar { a: b }",
        "web/src/opscenter/page-pair.css": ".oc-page__frame[data-pair] > .oc-page__side { a: b }",
        "web/src/opscenter/ui/Page.svelte": "<style>.oc-titlebar { a: b }</style>",
        "web/src/lib/x/x.css": ".oc-page.pledger { a: b } .oc-page__group { a: b } .oc-page__barx { a: b } /* .oc-page__bar { a: b } */",
    })
    assert fr.scan(repo) == {}


def test_negative_control_a_missing_or_empty_tree_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(fr.ScanError):
        fr.scan(tmp_path)
    (tmp_path / "web" / "src").mkdir(parents=True)
    with pytest.raises(fr.ScanError):
        fr.scan(tmp_path)


def test_negative_control_a_bare_header_or_aside_element_selector_goes_red(tmp_path: Path) -> None:
    repo = _tree(tmp_path, {"web/src/lib/x/x.css": ".pledger > header { a: b } .p aside { a: b } .ok[data-place='header'] { a: b } .headerx { a: b }"})
    assert fr.rows(fr.scan(repo)) == ["web/src/lib/x/x.css::.p aside", "web/src/lib/x/x.css::.pledger > header"]


def test_a_repeated_selector_in_one_file_is_a_row_each(tmp_path: Path) -> None:
    repo = _tree(tmp_path, {"web/src/lib/x/x.css": ".oc-page__bar { a: b } @media (x) { .oc-page__bar { a: c } }"})
    assert fr.rows(fr.scan(repo)) == ["web/src/lib/x/x.css::.oc-page__bar", "web/src/lib/x/x.css::.oc-page__bar#2"]
