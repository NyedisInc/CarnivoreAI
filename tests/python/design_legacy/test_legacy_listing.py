from __future__ import annotations

from pathlib import Path

from scripts.design import legacy_listing as ll
from scripts.design.raw_controls import scan_created_controls

FOUND = ll.scan_all()
KNOWN = ll.load_known()


def test_scans_see_the_trees() -> None:
    assert sum(ll._flat(FOUND["dialog_frames"]).values()) >= 10
    assert sum(ll._flat(FOUND["css_raw_values"]).values()) > 500
    assert FOUND["tablists"] and FOUND["ts_controls"]


def test_no_list_grew() -> None:
    grown, _stale = ll.compare(FOUND, KNOWN)
    assert not grown, "a NEW legacy row (use ModalShell / Tabs / base tokens, or the base control):\n  " + "\n  ".join(grown)


def test_no_list_is_stale() -> None:
    _grown, stale = ll.compare(FOUND, KNOWN)
    assert not stale, "a count fell: lower it with `python3 -m scripts.design.legacy_listing --write`:\n  " + "\n  ".join(stale)


def test_negative_control_roles_are_counted_and_comments_are_not() -> None:
    code = "el.setAttribute('role', 'dialog');\n<div role=\"alertdialog\">\n<div role=\"tablist\">"
    assert ll.count_roles(code) == {"dialog_frames": 2, "tablists": 1}
    assert ll.count_roles("// role=\"dialog\"\n/* role=\"tablist\" */\n<!-- role=\"dialog\" -->") == {"dialog_frames": 0, "tablists": 0}


def test_negative_control_a_planted_dialog_goes_red(tmp_path: Path) -> None:
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "new-modal.js").write_text("box.innerHTML = '<div role=\"dialog\" aria-modal=\"true\"></div>';\n")
    found = ll.scan_roles(tmp_path, tmp_path)
    grown, _ = ll.compare(found, {})
    assert grown == ["dialog_frames js/new-modal.js: 1 > 0"]


def test_negative_control_a_planted_sheet_goes_red(tmp_path: Path) -> None:
    (tmp_path / "x.css").write_text(".a { gap: 10px; color: #fff }\n")
    grown, _ = ll.compare({"css_raw_values": ll.scan_css(tmp_path, tmp_path)}, {})
    assert grown == ["css_raw_values x.css color: 1 > 0", "css_raw_values x.css spacing: 1 > 0"]


def test_negative_control_created_controls_count_code_not_comments(tmp_path: Path) -> None:
    (tmp_path / "a.ts").write_text("// document.createElement('button')\nconst b = document.createElement('button');\nconst i = doc.createElement(\"input\");\n")
    (tmp_path / "a.test.ts").write_text("document.createElement('button');\n")
    assert scan_created_controls(tmp_path, tmp_path) == {"a.ts": 2}


def test_lowered_never_raises_a_row_and_never_adds_one() -> None:
    known = {"tablists": {"a.js": 2, "gone.js": 1}, "css_raw_values": {"x.css": {"color": 3, "spacing": 1}}}
    found = {"tablists": {"a.js": 3, "new.js": 1}, "css_raw_values": {"x.css": {"color": 1, "spacing": 4}}}
    kept = ll.lowered(found, known)
    assert kept["tablists"] == {"a.js": 2}
    assert kept["css_raw_values"] == {"x.css": {"color": 1, "spacing": 1}}
    assert kept["dialog_frames"] == {} and kept["ts_controls"] == {}


def test_write_refuses_while_a_row_grew_and_changes_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    fixture = tmp_path / "known.json"
    known = {name: {} for name in ll.SECTIONS}
    known["tablists"] = {"a.js": 1}
    ll.write_known(known, fixture)
    before = fixture.read_text(encoding="utf-8")
    grew = {name: {} for name in ll.SECTIONS}
    grew["tablists"] = {"a.js": 2}
    monkeypatch.setattr(ll, "FIXTURE", fixture)
    monkeypatch.setattr(ll, "scan_all", lambda: grew)
    assert ll.main(["--write"]) == 1
    assert "GREW  tablists a.js: 2 > 1" in capsys.readouterr().out
    assert fixture.read_text(encoding="utf-8") == before
    grew["tablists"] = {"a.js": 0, "z.js": 5}
    assert ll.main(["--write"]) == 1 and fixture.read_text(encoding="utf-8") == before
    monkeypatch.setattr(ll, "scan_all", lambda: {name: {} for name in ll.SECTIONS})
    assert ll.main(["--write"]) == 0
    assert ll.json.loads(fixture.read_text(encoding="utf-8"))["sections"]["tablists"] == {}


def test_a_later_kind_is_first_measured_once_then_only_falls() -> None:
    kind = "radius"
    found = {"css_raw_values": {"x.css": {"spacing": 1, kind: 2}, "y.css": {kind: 1, "color": 1}}}
    known = {"css_raw_values": {"x.css": {"spacing": 1}}}
    admitted = ll.first_measured(found, known)
    assert admitted["css_raw_values"] == {"x.css": {"spacing": 1, kind: 2}, "y.css": {kind: 1}}
    assert known == {"css_raw_values": {"x.css": {"spacing": 1}}}
    later = {"css_raw_values": {"x.css": {"spacing": 1, kind: 3}, "y.css": {kind: 1}, "z.css": {kind: 1}}}
    grown, _ = ll.compare(later, ll.first_measured(later, admitted))
    assert grown == [f"css_raw_values x.css {kind}: 3 > 2", f"css_raw_values z.css {kind}: 1 > 0"]


def test_the_js_controls_scan_sees_client_js() -> None:
    rows = FOUND["js_controls"]
    assert len(rows) > 20 and all(any(k in c for c in rows.values()) for k in ll.JS_KINDS)


def test_negative_control_js_controls_count_code_not_comments() -> None:
    code = ("el.innerHTML = '<button>a</button><input>';\nconst b = document.createElement('button');\n"
            "const s = document.createElement(\"select\");\nwrap.insertAdjacentHTML('beforeend', '<textarea></textarea>');\n")
    assert ll.count_js(code) == {"dom-write": 4, "button": 2, "field": 3}
    quiet = "// createElement('button')\n/* el.innerHTML = '<input>' */\nif (el.innerHTML == x) {}\nconst u = 'http://a/b'; // <button>\n"
    assert ll.count_js(quiet) == {"dom-write": 0, "button": 0, "field": 0}
    assert ll.count_js("const t = '<buttons>'; const i = '<inputs>';") == {"dom-write": 0, "button": 0, "field": 0}


def test_negative_control_a_legacy_file_growing_inside_its_row_goes_red() -> None:
    rel, kinds = next(iter(KNOWN["js_controls"].items()))
    grown_found = {**FOUND, "js_controls": {**FOUND["js_controls"], rel: {**kinds, "button": kinds.get("button", 0) + 1}}}
    grown, _stale = ll.compare(grown_found, KNOWN)
    assert any(line.startswith(f"js_controls {rel}") or rel in line and "button" in line for line in grown), grown


def test_the_js_controls_section_was_first_measured_and_a_missing_tree_is_never_clean(tmp_path: Path) -> None:
    admitted = ll.first_measured(FOUND, {k: v for k, v in KNOWN.items() if k != "js_controls"})
    assert admitted["js_controls"] == FOUND["js_controls"]
    try:
        ll.scan_js(tmp_path / "absent", tmp_path)
    except FileNotFoundError:
        return
    raise AssertionError("a missing client/js read as clean")
