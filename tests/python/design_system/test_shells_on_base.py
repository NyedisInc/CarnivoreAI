from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.design import raw_controls as rc
from scripts.design import raw_values as rv

SHELL_FOLDERS = (
    "web/src/lib/manager-frame/",
    "web/src/opscenter/shell/",
    "web/src/opscenter/ui/",
)


def shell_rows(baseline: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    return {path: kinds for path, kinds in baseline.items() if path.startswith(SHELL_FOLDERS)}


EXEMPT_KIND = "exempt"


def raw_only(rows: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    kept = {p: {k: n for k, n in kinds.items() if k != EXEMPT_KIND} for p, kinds in rows.items()}
    return {p: kinds for p, kinds in kept.items() if kinds}


def _values_baseline() -> dict[str, dict[str, int]]:
    return json.loads(rv.BASELINE.read_text(encoding="utf-8"))["files"]


def test_no_raw_controls_baseline_row_in_the_shell_folders() -> None:
    rows = raw_only(shell_rows(rc.load_baseline()))
    assert not rows, f"the shells are on the base; raw-controls rows must stay absent, found: {rows}"


def test_no_raw_values_baseline_row_in_the_shell_folders() -> None:
    rows = shell_rows(_values_baseline())
    assert not rows, f"the shells read --oc-* tokens only; raw-values rows must stay absent, found: {rows}"


def test_the_live_scan_finds_nothing_in_the_shell_folders() -> None:
    assert not raw_only(shell_rows(rc.scan())), "a raw button or field is back in a shell folder"
    assert not shell_rows(rv.scan()), "a raw spacing, font or color value is back in a shell folder"


def test_negative_control_a_shell_row_in_a_baseline_is_found() -> None:
    planted = {"web/src/opscenter/shell/TopBar.svelte": {"buttons": 2}, "web/src/lib/other/Elsewhere.svelte": {"buttons": 9}}
    assert shell_rows(planted) == {"web/src/opscenter/shell/TopBar.svelte": {"buttons": 2}}


def test_negative_control_a_planted_raw_button_in_a_shell_folder_is_found(tmp_path: Path) -> None:
    src = tmp_path / "web" / "src" / "lib" / "manager-frame"
    src.mkdir(parents=True)
    (src / "Planted.svelte").write_text("<button>x</button>\n<style>.a { gap: 5px; }</style>\n")
    root = tmp_path / "web" / "src"
    assert shell_rows(rc.scan(root, tmp_path)) == {"web/src/lib/manager-frame/Planted.svelte": {"buttons": 1}}
    assert shell_rows(rv.scan(root, tmp_path)) == {"web/src/lib/manager-frame/Planted.svelte": {"spacing": 1}}


def test_negative_control_exempt_is_ignored_but_a_raw_kind_beside_it_is_not() -> None:
    assert raw_only({"web/src/opscenter/ui/SplitButton.svelte": {"exempt": 1}}) == {}
    both = {"web/src/opscenter/ui/X.svelte": {"exempt": 1, "buttons": 1}}
    assert raw_only(both) == {"web/src/opscenter/ui/X.svelte": {"buttons": 1}}


PUBLISH_PAGE_PREFIX = "web/src/lib/publish-page/"
PP_TOKEN = "--oc-pp-space-"
TOKENS_FILE = "web/src/opscenter/tokens.css"


def pp_space_strays(root: Path, repo: Path) -> list[str]:
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".svelte", ".css", ".ts"}:
            continue
        rel = path.relative_to(repo).as_posix()
        if rel.startswith(PUBLISH_PAGE_PREFIX) or rel == TOKENS_FILE:
            continue
        if PP_TOKEN in path.read_text(encoding="utf-8", errors="replace"):
            found.append(rel)
    return found


def test_the_publish_pages_spacing_scale_stays_the_publish_pages() -> None:
    repo = rc.REPO
    assert not pp_space_strays(repo / "web" / "src", repo), "a file outside publish-page/ reads --oc-pp-space-*"


def test_negative_control_a_borrowed_publish_page_token_is_found(tmp_path: Path) -> None:
    shell = tmp_path / "web" / "src" / "opscenter" / "shell"
    shell.mkdir(parents=True)
    (shell / "Borrower.svelte").write_text("<style>.a { gap: var(--oc-pp-space-10); }</style>\n")
    page = tmp_path / "web" / "src" / "lib" / "publish-page"
    page.mkdir(parents=True)
    (page / "Own.css").write_text(".a { gap: var(--oc-pp-space-10); }\n")
    assert pp_space_strays(tmp_path / "web" / "src", tmp_path) == ["web/src/opscenter/shell/Borrower.svelte"]


CANCEL = re.compile(r"--_btn-(?:h:\s*0(?:px)?|lh:\s*normal)\s*;")
OWN_BOX_ATTRS = ("auto", "bare")


def cancelling_the_base(root: Path, repo: Path) -> list[str]:
    found = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(repo).as_posix()
        if path.is_file() and path.suffix in {".svelte", ".css"} and rel.startswith(SHELL_FOLDERS) and CANCEL.search(path.read_text(encoding="utf-8", errors="replace")):
            found.append(rel)
    return found


def test_no_shell_cancels_the_base_button_through_its_private_variables() -> None:
    repo = rc.REPO
    assert not cancelling_the_base(repo / "web" / "src", repo), "a shell sets --_btn-h: 0 or --_btn-lh: normal; use data-size=auto or bare"


def test_the_base_owns_the_variants_and_the_mask_stays_opaque() -> None:
    sheet = (rc.REPO / "web/src/lib/base/elements.css").read_text(encoding="utf-8")
    assert all(f"[data-btn][data-size='{name}']" in sheet for name in OWN_BOX_ATTRS) and "[data-btn][data-overflow='visible']" in sheet
    tabs = (rc.REPO / "web/src/opscenter/ui/tabs.css").read_text(encoding="utf-8")
    assert "currentColor" not in tabs and "var(--oc-mask-solid)" in tabs, "a fade mask must be opaque whatever the text color is"


def test_negative_control_a_hand_cancelled_base_is_found(tmp_path: Path) -> None:
    ui = tmp_path / "web" / "src" / "opscenter" / "ui"
    ui.mkdir(parents=True)
    (ui / "Bad.svelte").write_text("<style>.a { --_btn-h: 0px; --_btn-lh: normal; }</style>\n")
    (ui / "Good.svelte").write_text("<style>.a { --_btn-h: var(--oc-space-4); }</style>\n")
    elsewhere = tmp_path / "web" / "src" / "opscenter" / "fields.css"
    elsewhere.write_text(".oc-chip { --_btn-h: 0px; }\n")
    assert cancelling_the_base(tmp_path / "web" / "src", tmp_path) == ["web/src/opscenter/ui/Bad.svelte"]


SHELL_TOKEN_PIXELS = {
    "--oc-gap-hair": "1px", "--oc-pad-snug": "3px", "--oc-gap-mark": "7px", "--oc-gap-parts": "10px", "--oc-card-pad-y": "10px",
    "--oc-cell-pad-x": "10px", "--oc-tab-end-pad": "14px", "--oc-topbar-pad-left": "22px", "--oc-topbar-word-gap": "9px",
    "--oc-topbar-chip-gap": "18px", "--oc-head-chevron-room": "21px", "--oc-fs-tab-numeral": "calc(var(--oc-fs-figure) * 2)",
    "--oc-mask-solid": "#000", "--oc-fs-status": "13px", "--oc-fs-body": "12px",
}


def token_values(css: str) -> dict[str, str]:
    plain = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    values: dict[str, str] = {}
    for name, value in re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", plain):
        values.setdefault(name, " ".join(value.split()))
    return values


def test_the_shell_tokens_keep_the_pixels_the_shells_always_drew() -> None:
    values = token_values((rc.REPO / "web/src/opscenter/tokens.css").read_text(encoding="utf-8"))
    moved = {name: (want, values.get(name)) for name, want in SHELL_TOKEN_PIXELS.items() if values.get(name) != want}
    assert not moved, f"a shell token moved off the pixels the shells drew (wanted, found): {moved}"


def test_negative_control_a_moved_shell_token_is_found() -> None:
    values = token_values(":root { --oc-gap-parts: 11px; /* a comment: --oc-pad-snug: 9px; */ }")
    assert values == {"--oc-gap-parts": "11px"} and values["--oc-gap-parts"] != SHELL_TOKEN_PIXELS["--oc-gap-parts"]
