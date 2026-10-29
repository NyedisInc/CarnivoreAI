
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib" / "edit_layout.py"
WEB = REPO / "web" / "src"
EDIT_LAYOUT_SCRIPTS = (
    "verify_layouts_page.py", "verify_layout_editor.py", "verify_keep_awake_visible.py",
    "verify_session_timers.py", "verify_widget_settings.py", "verify_terminal_tabs_drag.py",
)
ALL_SCRIPTS = sorted([*(REPO / "scripts").glob("verify_*.py"), *(REPO / "scripts" / "lib").glob("*.py")])
STALE_MARKERS = ('data-action="add-component"', '#session-sidebar-bar-slot [data-bar-action="layout"]')


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("edit_layout_under_test", LIB)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = _load()


def _src(*parts: str) -> str:
    return WEB.joinpath(*parts).read_text(encoding="utf-8")


def _attr(selector: str) -> str:
    found = re.search(r"\[([^\]]+)\]", selector)
    assert found, selector
    return found.group(1)


def test_account_chip_is_drawn_by_the_drawer_bar() -> None:
    assert _attr(MOD.ACCOUNT_CHIP) in _src("lib", "drawer", "DrawerBar.svelte")


def test_edit_layout_item_is_the_account_menus_layout_node_in_the_cascade_menu() -> None:
    node = re.search(r'data-node="(\w+)"', MOD.EDIT_LAYOUT_ITEM)
    assert node and MOD.EDIT_LAYOUT_ITEM.startswith(".acm-menu ")
    assert f"id: '{node.group(1)}'" in _src("lib", "drawer-hud", "AccountMenu.svelte")
    cascade = _src("lib", "drawer-tabs", "CascadeMenu.svelte")
    assert 'class="acm-menu' in cascade
    assert re.search(r'class="acm-item"(?:(?!</button>).)*data-node=\{node\.id\}', cascade, re.DOTALL)


def test_blocked_item_is_drawn_aria_disabled() -> None:
    assert "blocked:" in _src("lib", "drawer-hud", "AccountMenu.svelte")
    assert "aria-disabled={node.blocked" in _src("lib", "drawer-tabs", "CascadeMenu.svelte")


@pytest.mark.parametrize("constant", ["EDITOR_DRAWER", "EDITOR_DONE"])
def test_editor_markers_are_drawn_by_the_widget_drawer(constant: str) -> None:
    assert _attr(getattr(MOD, constant)) in _src("opscenter", "layout-editor", "WidgetDrawer.svelte")


def test_the_fold_names_are_the_widget_drawers_window_kinds() -> None:
    drawer = _src("opscenter", "layout-editor", "WidgetDrawer.svelte")
    rows = _src("opscenter", "layout-editor", "WindowRows.svelte")
    for kind in MOD.PICKER_FOLDS:
        assert f"'{kind}'" in re.search(r"showSessionEntries \? \(\[([^\]]*)\]", drawer).group(1)  # type: ignore[union-attr]
    assert "data-picker-entry={kind}" in rows and "data-picker-row={choice.id}" in rows


def test_modal_and_refusal_markers_exist() -> None:
    assert _attr(MOD.LAYOUT_NAME_MODAL) in _src("opscenter", "layouts", "LayoutNameModal.svelte")
    assert f'class="le-wfold__hint {MOD.PICKER_REFUSAL.lstrip(".")}"' in _src("opscenter", "layout-editor", "WindowRows.svelte")


def test_the_glob_found_scripts() -> None:
    assert len(ALL_SCRIPTS) >= 10 and LIB in ALL_SCRIPTS


@pytest.mark.parametrize("path", ALL_SCRIPTS, ids=lambda p: p.name)
def test_no_script_names_a_removed_control(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not [m for m in STALE_MARKERS if m in text]


@pytest.mark.parametrize("name", EDIT_LAYOUT_SCRIPTS)
def test_each_edit_layout_script_uses_the_shared_opener(name: str) -> None:
    assert "scripts.lib.edit_layout import" in (REPO / "scripts" / name).read_text(encoding="utf-8")


def test_plus_pick_selectors_match_the_plus_menu_source() -> None:
    assert 'classes="oc-tab-new"' in _src("opscenter", "shell", "TabStrip.svelte")
    assert "data-level={level}" in _src("lib", "drawer-tabs", "CascadeMenu.svelte")
    assert "'agent'" in _src("lib", "drawer-tabs", "drawer-tabs.ts")


class _Loc:

    def __init__(self, page: "_Page", sel: str) -> None:
        self.page, self.sel = page, sel

    @property
    def first(self) -> "_Loc":
        return self

    def click(self) -> None:
        self.page.clicks.append(self.sel)
        if self.sel == MOD.EDIT_LAYOUT_ITEM:
            self.page.active = not self.page.active
        if self.sel == MOD.EDITOR_DONE:
            if MOD.LAYOUT_NAME_MODAL in self.page.present:
                raise AssertionError("Done pressed under the naming modal")
            self.page.active = False

    def count(self) -> int:
        return 1 if self.sel in self.page.present else 0

    def get_attribute(self, name: str) -> str | None:
        return self.page.attrs.get((self.sel, name))

    def wait_for(self, **_: Any) -> None:
        self.page.waited.append(self.sel)


class _Page:

    def __init__(self, present: set[str], attrs: dict[tuple[str, str], str] | None = None, active: bool = False) -> None:
        self.present, self.attrs, self.active = present, attrs or {}, active
        self.clicks: list[str] = []
        self.waited: list[str] = []

    def locator(self, sel: str) -> _Loc:
        return _Loc(self, sel)

    def evaluate(self, script: str, *_: Any) -> bool | None:
        return self.active if "layoutEditor" in script else None

    def wait_for_timeout(self, *_: Any) -> None:
        return None

    @property
    def keyboard(self) -> "_Page":
        return self

    def press(self, *_: Any) -> None:
        return None


ROW = '[data-picker-row="ses_b"]'
SESSION = '[data-picker-entry="session"]'


def test_free_session_row_is_added_and_edit_layout_is_left() -> None:
    page = _Page({ROW})
    assert MOD.add_window(page, {"id": "ses_b"}) == MOD.ADDED
    assert page.clicks == [MOD.ACCOUNT_CHIP, MOD.EDIT_LAYOUT_ITEM, SESSION, ROW, MOD.EDITOR_DONE]


def test_terminal_member_is_found_in_the_second_fold() -> None:
    row = '[data-picker-row="ses_t"]'

    class Late(_Page):
        def locator(self, sel: str) -> _Loc:
            if sel == row and '[data-picker-entry="terminal"]' not in self.clicks:
                return _Loc(_Page(set()), sel)
            return super().locator(sel)

    page = Late({row})
    assert MOD.add_window(page, {"id": "ses_t"}) == MOD.ADDED
    assert page.clicks[-3:] == ['[data-picker-entry="terminal"]', row, MOD.EDITOR_DONE]


def test_an_editor_that_is_already_on_is_not_toggled_off() -> None:
    page = _Page({ROW}, active=True)
    MOD.open_edit_layout(page)
    assert MOD.EDIT_LAYOUT_ITEM not in page.clicks and page.active is True


def test_the_naming_modal_leaves_done_unpressed_and_the_caller_finishes_after_answering_it() -> None:
    page = _Page({ROW, MOD.LAYOUT_NAME_MODAL})
    assert MOD.add_window(page, {"id": "ses_b"}) == MOD.MODAL_OPEN
    assert MOD.EDITOR_DONE not in page.clicks and page.active is True
    page.present.discard(MOD.LAYOUT_NAME_MODAL)
    MOD.finish_edit_layout(page)
    assert page.clicks[-1] == MOD.EDITOR_DONE and page.active is False


def test_a_refused_add_is_reported_and_edit_layout_is_still_left() -> None:
    page = _Page({ROW, MOD.PICKER_REFUSAL})
    assert MOD.add_window(page, {"id": "ses_b"}) == MOD.REFUSED
    assert page.clicks[-1] == MOD.EDITOR_DONE


def test_missing_or_already_placed_member_is_missing_and_still_clicks_done() -> None:
    for page in (_Page(set()), _Page({ROW}, {(ROW, "aria-disabled"): "true"})):
        assert MOD.add_window(page, {"id": "ses_b"}) == MOD.MISSING
        assert page.clicks[-1] == MOD.EDITOR_DONE and ROW not in page.clicks


def test_done_runs_even_when_the_pick_raises() -> None:
    class Boom(_Page):
        def locator(self, sel: str) -> _Loc:
            if sel == SESSION:
                raise RuntimeError("page closed")
            return super().locator(sel)

    page = Boom({ROW})
    with pytest.raises(RuntimeError):
        MOD.add_window(page, {"id": "ses_b"})
    assert page.clicks[-1] == MOD.EDITOR_DONE and page.active is False


def test_a_greyed_out_item_is_not_offered() -> None:
    assert MOD.edit_layout_offered(_Page({MOD.EDIT_LAYOUT_ITEM})) is True
    assert MOD.edit_layout_offered(_Page({MOD.EDIT_LAYOUT_ITEM}, {(MOD.EDIT_LAYOUT_ITEM, "aria-disabled"): "true"})) is False
    assert MOD.edit_layout_offered(_Page(set())) is False


def test_a_drawer_that_never_shows_ends_the_mode_before_raising() -> None:
    class Hidden(_Page):
        def locator(self, sel: str) -> _Loc:
            loc = super().locator(sel)
            if sel == MOD.EDITOR_DRAWER:
                loc.wait_for = lambda **_: (_ for _ in ()).throw(TimeoutError("drawer hidden"))  # type: ignore[method-assign]
            return loc

    page = Hidden(set())
    with pytest.raises(TimeoutError):
        MOD.open_edit_layout(page)
    assert page.clicks[-1] == MOD.EDITOR_DONE and page.active is False
