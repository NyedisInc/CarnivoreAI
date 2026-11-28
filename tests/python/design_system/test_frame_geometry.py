from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from scripts.design import frame_geometry as fg
from scripts.design import frame_geometry_run as run


def _button(name: str, h: float, w: float | None = None, icon: bool = False) -> dict[str, Any]:
    return {"name": name, "icon": icon, "w": w if w is not None else (h if icon else 60), "h": h}


def _root(header_h: float | None, buttons: list[dict[str, Any]], sides: tuple[float, ...] = ()) -> dict[str, Any]:
    return {"frame": "nav", "header": None if header_h is None else {"w": 900, "h": header_h}, "buttons": buttons,
            "sides": [{"w": w, "h": 600} for w in sides]}


def test_menu_pages_reads_every_entry() -> None:
    source = fg.MENU_PAGES_TS.read_text()
    entries = len(re.findall(r"containerId:\s*'", source))
    pages = fg.menu_pages()
    assert entries >= 20 and len(pages) == entries, f"read {len(pages)} of {entries} MENU_PAGES entries"
    assert all(p.hash.startswith("#") and p.frame in {"column", "nav", "canvas"} for p in pages)


def test_menu_pages_without_entries_cannot_determine(tmp_path: Path) -> None:
    with pytest.raises(fg.GeometryError):
        fg.menu_pages(tmp_path / "missing.ts")
    empty = tmp_path / "menu-pages.ts"
    empty.write_text("export const MENU_PAGES = [];\n")
    with pytest.raises(fg.GeometryError):
        fg.menu_pages(empty)


@pytest.mark.parametrize("layout", fg.LAYOUTS, ids=lambda layout: layout.name)
def test_the_ruled_page_is_green(layout: fg.Layout) -> None:
    root = _root(layout.header_h, [_button("save", layout.button_h), _button("close", layout.button_h, icon=True)], (fg.SIDE_W,))
    assert fg.check_page("sessions", [root], layout) == []


def test_the_old_pages_go_red() -> None:
    roots = [_root(44, [_button("new", 22), _button("close", 28, icon=True), _button("flip", 26, w=30, icon=True)], (240, 300))]
    assert fg.check_page("automations", roots, fg.DESKTOP) == [
        "desktop::automations::button close 28 != 26",
        "desktop::automations::button new 22 != 26",
        "desktop::automations::header 44 != 37",
        "desktop::automations::icon flip not square",
        "desktop::automations::side 240 != 208",
        "desktop::automations::side 300 != 208",
    ]


def test_a_phone_page_holds_the_tap_size() -> None:
    assert fg.check_page("warez", [_root(56, [_button("all", 26)])], fg.PHONE) == ["phone::warez::button all 26 != 44"]


def test_a_page_with_no_header_or_no_root_is_caught() -> None:
    with pytest.raises(fg.GeometryError):
        fg.check_page("widgets", [], fg.DESKTOP)
    assert fg.check_page("widgets", [_root(None, [])], fg.DESKTOP) == ["desktop::widgets::no header"]


def test_the_old_swarm_slide_out_goes_red() -> None:
    old = {"id": "core.swarm", "rows": [], "buttons": [
        _button("swarm", 20), _button("open the swarm page", 22, icon=True), _button("close", 28, icon=True)]}
    assert fg.check_flyout(old, "core.swarm", fg.DESKTOP) == [
        "desktop::core.swarm::flyout button close 28 != 26",
        "desktop::core.swarm::flyout button open the swarm page 22 != 26",
        "desktop::core.swarm::flyout button swarm 20 != 26",
    ]
    ruled = {"id": "core.swarm", "rows": [], "buttons": [_button("swarm", 26), _button("close", 26, icon=True)]}
    assert fg.check_flyout(ruled, "core.swarm", fg.DESKTOP) == []


def test_a_second_title_row_in_a_slide_out_body_goes_red() -> None:
    found = {"id": "core.questions", "buttons": [], "rows": ["pl-titlebar", "pl-titlebar", "oc-titlebar"]}
    assert fg.check_flyout(found, "core.questions", fg.DESKTOP) == [
        "desktop::core.questions::flyout second title row oc-titlebar",
        "desktop::core.questions::flyout second title row pl-titlebar",
    ]


def test_a_slide_out_that_did_not_open_cannot_determine() -> None:
    with pytest.raises(fg.GeometryError):
        fg.check_flyout(None, "core.swarm", fg.DESKTOP)
    with pytest.raises(fg.GeometryError):
        fg.check_flyout({"id": "core.menu", "buttons": [], "rows": []}, "core.swarm", fg.DESKTOP)


def test_the_title_row_selector_names_the_canonical_strips() -> None:
    for strip in (".oc-titlebar", ".pl-titlebar", ".oc-frame-title", ".sbr-flyout__title"):
        assert strip in fg.TITLE_ROWS


SLOT = ["--base", "http://127.0.0.1:8101", "--storage-state", "/nonexistent/auth.json"]


def test_the_runner_without_playwright_cannot_determine(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(run, "load_playwright", lambda: None)
    assert run.main(SLOT) == 2
    assert "CANNOT DETERMINE" in capsys.readouterr().out


class _NoBrowser:

    class chromium:  # noqa: N801
        @staticmethod
        def launch() -> None:
            raise RuntimeError("Executable doesn't exist")

    def __enter__(self) -> "_NoBrowser":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_the_runner_without_a_browser_cannot_determine(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(run, "load_playwright", lambda: _NoBrowser)
    monkeypatch.setattr(run, "call", lambda *a, **k: pytest.fail("the slot was called before the browser launched"))
    assert run.main(SLOT) == 2
    assert "could not launch" in capsys.readouterr().out


def test_the_runner_refuses_the_live_install(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--base", "http://127.0.0.1:8000", "--storage-state", "/nonexistent/auth.json"]) == 2
    assert "CANNOT DETERMINE" in capsys.readouterr().out


def test_the_verdict_needs_a_measurement() -> None:
    assert run.verdict(fg.Findings()) == 2
    assert run.verdict(fg.Findings(pages={"desktop::sessions"})) == 2
    assert run.verdict(fg.Findings(rows={"desktop::sessions::header 44 != 37"}, pages={"desktop::sessions"}, flyouts={"core.swarm"})) == 1
    assert run.verdict(fg.Findings(pages={"desktop::sessions"}, flyouts={"core.swarm"})) == 0


def test_a_page_not_offered_on_a_phone_is_skipped_only_there() -> None:
    warroom = fg.MenuPage("warroom", "warroom-screen", "#warroom", "canvas")
    plugins = fg.MenuPage("plugins", "plugins-screen", "#plugins", "column")
    assert not fg.offered(warroom, fg.PHONE)
    assert fg.offered(warroom, fg.DESKTOP)
    assert fg.offered(plugins, fg.PHONE)


def test_each_phone_skip_is_still_what_its_source_says() -> None:
    assert fg.NOT_ON_PHONE, "nothing listed, so nothing was checked"
    for page_id, source in fg.NOT_ON_PHONE.items():
        path = fg.REPO / source
        assert path.is_file(), f"{page_id}: {source} is gone, so the phone skip has no reason"
        assert "!phoneView()" in path.read_text(), f"{page_id}: {source} no longer hides the page on a phone; measure it there"
    assert any(page.id in fg.NOT_ON_PHONE for page in fg.menu_pages()), "a NOT_ON_PHONE id names no drawer page"


def test_a_drawer_pair_list_keeps_its_content_width() -> None:
    pair_list = dict(_root(37, [], sides=(240,)), pair="list")
    assert fg.check_page("settings", [pair_list], fg.DESKTOP) == []
    assert fg.check_page("sessions", [_root(37, [], sides=(240,))], fg.DESKTOP) == ["desktop::sessions::side 240 != 208"]
