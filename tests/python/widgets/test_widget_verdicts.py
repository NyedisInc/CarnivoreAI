
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from scripts.widgets import harness
from scripts.widgets.catalog_meta import write_catalog_metadata
from scripts.widgets.fit_table import build_table, write_table
from scripts.widgets.harness import Render
from scripts.widgets.verdicts import FAIL, PASS, UNSUPPORTED, cells_of, host_of, run_verdict, unsupported_run


def draw(zone: str = "home", size: str = "m", theme: str = "carnivore", fixture: str = "data", **over: Any) -> Render:
    return Render(key="core.notes", zone=zone, size=size, fixture=fixture, theme=theme, **over)


def finding(rule: str = "overflow-x", px: int = 12) -> dict:
    return {"rule": rule, "selector": ".x", "px": px, "detail": f"{rule} by {px}px"}


def test_a_clean_draw_passes() -> None:
    assert run_verdict(draw()) == {"verdict": PASS, "reasons": [], "red": False}


@pytest.mark.parametrize("over,needle", [
    ({"error": "the widget threw"}, "draw error: the widget threw"),
    ({"console": ["TypeError: x is undefined"]}, "console error: TypeError"),
    ({"findings": [finding("bad-text")]}, "bad-text"),
])
def test_a_draw_that_errors_logs_or_has_a_finding_fails_with_its_reason(over: dict, needle: str) -> None:
    verdict = run_verdict(draw(**over))
    assert verdict["verdict"] == FAIL and any(needle in r for r in verdict["reasons"]), verdict


def test_clipping_and_overflow_are_red_and_other_findings_are_not() -> None:
    assert run_verdict(draw(findings=[finding("clipped-text")]))["red"] is True
    assert run_verdict(draw(findings=[finding("overflow-y")]))["red"] is True
    assert run_verdict(draw(findings=[finding("bad-text")]))["red"] is False
    assert run_verdict(draw(error="boom"))["red"] is True


def test_the_unsupported_verdict_is_never_a_pass_or_red() -> None:
    verdict = unsupported_run("core.notes", "popout", "xl", "the widget does not declare it")
    assert verdict["verdict"] == UNSUPPORTED and verdict["red"] is False and "core.notes popout/xl" in verdict["reasons"][0]


def test_the_glance_row_is_its_own_host() -> None:
    assert host_of(draw(zone="drawer", size="glance")) == "glance"
    assert host_of(draw(zone="drawer", size="m")) == "drawer"


def test_a_cell_is_the_worst_of_every_theme_and_fixture() -> None:
    renders = [draw(theme="carnivore"), draw(theme="acid_trip", findings=[finding()]), draw(fixture="empty")]
    (cell,) = cells_of(renders, ["home"])
    assert cell["verdict"] == FAIL and cell["draws"] == 3 and cell["red"] is True
    assert cell["themes"] == ["acid_trip", "carnivore"] and cell["fixtures"] == ["data", "empty"]
    assert len(cell["reasons"]) == 1


def test_a_declared_pair_nobody_drew_fails() -> None:
    cells = cells_of([draw()], ["home"], {"terminal/wide": "declared but never drawn"})
    gone = next(c for c in cells if c["host"] == "terminal")
    assert gone["verdict"] == FAIL and gone["draws"] == 0


def test_a_declared_popout_follows_the_home_cells_and_an_undeclared_one_does_not() -> None:
    renders = [draw(size="s"), draw(size="m", findings=[finding()])]
    with_popout = {(c["host"], c["size"]): c for c in cells_of(renders, ["home", "popout"])}
    assert with_popout[("popout", "m")]["verdict"] == FAIL and with_popout[("popout", "s")]["verdict"] == PASS
    assert all(c["host"] != "popout" for c in cells_of(renders, ["home"]))


def gate_with(widget: str, cells: list[dict], ok: bool = True, determined: bool = True) -> dict:
    return {"widget": widget, "ok": ok, "determined": determined, "failures": [] if ok else ["x"], "cells": cells}


def cell(host: str, size: str, verdict: str = PASS) -> dict:
    return {"host": host, "size": size, "verdict": verdict, "red": verdict == FAIL, "draws": 2, "reasons": [] if verdict == PASS else ["why"]}


def test_the_table_marks_a_host_or_size_a_widget_lacks_as_unsupported() -> None:
    table = build_table([gate_with("a.one", [cell("home", "m"), cell("terminal", "m")]), gate_with("b.two", [cell("home", "m")])])
    assert table["hosts"] == {"home": ["m"], "terminal": ["m"]}
    assert table["widgets"][1]["cells"]["terminal/m"]["verdict"] == UNSUPPORTED
    assert table["counts"] == {PASS: 3, FAIL: 0, UNSUPPORTED: 1}


def test_a_failing_cell_and_an_undetermined_widget_show_in_the_table() -> None:
    table = build_table([gate_with("a.one", [cell("home", "m", FAIL)], ok=False), gate_with("b.two", [], ok=False, determined=False)])
    assert table["counts"][FAIL] == 1
    assert table["widgets"][0]["cells"]["home/m"]["red"] is True
    assert table["widgets"][1]["determined"] is False and table["widgets"][1]["ok"] is False


def test_the_table_is_written_as_json(tmp_path: Path) -> None:
    path = write_table(tmp_path, [gate_with("a.one", [cell("home", "m")])], {"sha": "abc", "dirty": False})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "fit-table.json" and data["schema"] == 1 and data["source_revision"]["sha"] == "abc"


def png(path: Path, w: int = 3, h: int = 2) -> None:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    rows = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def test_catalog_metadata_names_every_image_and_skips_an_empty_folder(tmp_path: Path) -> None:
    folder = tmp_path / "features" / "media" / "widgets" / "core.notes"
    folder.mkdir(parents=True)
    assert write_catalog_metadata(folder, "core.notes", "carnivore") is None and not (folder / "capture.json").exists()
    png(folder / "m.png")
    meta = json.loads(write_catalog_metadata(folder, "core.notes", "carnivore").read_text(encoding="utf-8"))
    assert meta["widget"] == "core.notes" and meta["theme"] == "carnivore" and meta["fixture"] == "data"
    assert meta["images"][0]["file"] == "m.png" and meta["images"][0]["pixels"] == [3, 2] and len(meta["images"][0]["sha256"]) == 64


class FakePage:

    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def on(self, name: str, handler: Any) -> None:
        self.handlers[name] = handler


class Message:

    def __init__(self, kind: str, text: str) -> None:
        self.type, self.text = kind, text


def test_console_errors_and_uncaught_errors_are_drained_but_resource_noise_is_not() -> None:
    page = FakePage()
    harness.watch_console(page)
    page.handlers["console"](Message("error", "TypeError: nope"))
    page.handlers["console"](Message("error", "Failed to load resource: the server responded with a status of 404"))
    page.handlers["console"](Message("warning", "just a warning"))
    page.handlers["pageerror"](RuntimeError("boom"))
    assert harness.drain_console(page) == ["TypeError: nope", "uncaught: boom"]
    assert harness.drain_console(page) == []
    assert harness.watch_console(page) is harness.watch_console(page)


def test_a_run_in_slices_reads_every_gate_record_into_one_table(tmp_path: Path) -> None:
    from scripts.widgets.fit_table import read_gates  # noqa: PLC0415
    for name in ("b.two", "a.one"):
        (tmp_path / f"{name}.gate.json").write_text(json.dumps(gate_with(name, [cell("home", "m")])), encoding="utf-8")
    (tmp_path / "summary.json").write_text("{}", encoding="utf-8")
    assert [g["widget"] for g in read_gates(tmp_path)] == ["a.one", "b.two"]
