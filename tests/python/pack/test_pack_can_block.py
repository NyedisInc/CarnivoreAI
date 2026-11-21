
from __future__ import annotations

import copy
import json
from typing import Any, Dict

import pytest

from src.core.pack.machines import can_block

PROBE: Dict[str, Any] = {
    "probed_at": 1000.0, "os": "macos", "os_version": "26.1", "arch": "arm64", "chip": "Apple M1 Max", "cores": 10, "mem_gb": 64.0,
    "gpus": [{"vendor": "apple", "model": "Apple M1 Max", "vram_gb": None, "discrete": False}],
    "tools": {"git": True, "ffmpeg": False, "playwright_browsers": True, "madeup": True}, "xcode": "16.1", "ios_sim": True, "brew": True}


def test_build_parses_and_drops_unknown_tools() -> None:
    block = can_block.build(PROBE, ["render box"], None)
    parsed = can_block.parse(block)
    assert parsed is not None and parsed.xcode == "16.1" and "madeup" not in parsed.tools and parsed.tools["git"] is True
    assert len(json.dumps(block)) <= can_block.MAX_BLOCK_BYTES


def test_received_unknown_tool_is_dropped_and_unknown_key_ignored() -> None:
    block = can_block.build(PROBE, [], None)
    block["tools"]["quantum"] = True
    block["from_the_future"] = {"x": 1}
    parsed = can_block.parse(block)
    assert parsed is not None and "quantum" not in parsed.tools


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(cores=0), lambda b: b.update(cores=5000), lambda b: b.update(cores="10"), lambda b: b.update(cores=True),
    lambda b: b.update(mem_gb=-1), lambda b: b.update(mem_gb=float("nan")), lambda b: b.update(rev="nothex"),
    lambda b: b.update(os="Mac OS X!"), lambda b: b.update(tools={"git": "yes"}), lambda b: b.update(tools=["git"]),
    lambda b: b.update(labels=["Bad Label"]), lambda b: b.update(labels=["a"] * 17),
    lambda b: b.update(gpus=[{"vendor": "matrox", "model": "x", "vram_gb": 1, "discrete": True}]),
    lambda b: b.update(gpus=[{"vendor": "amd", "model": "x" * 65, "vram_gb": 1, "discrete": True}]),
    lambda b: b["gpus"].extend([b["gpus"][0]] * 4), lambda b: b.update(xcode="16.1; rm"), lambda b: b.pop("rev"),
    lambda b: b.update(installing="a b"), lambda b: b.update(v=0),
])
def test_invalid_block_reads_as_absent(mutate: Any) -> None:
    block = copy.deepcopy(can_block.build(PROBE, [], None))
    mutate(block)
    assert can_block.parse(block) is None


@pytest.mark.parametrize("raw", [None, "x", 5, [], {}, {"v": 1}])
def test_non_block_values_are_absent(raw: Any) -> None:
    assert can_block.parse(raw) is None


def test_a_real_full_snapshot_stays_under_the_16_kib_receiver_cap(tmp_path: Any) -> None:
    from src.core.pack.machines import roster
    from src.core.pack.machines.snapshot import SnapshotCollector
    from src.core.pack.reserve.holds import Holds
    from src.core.pack.reserve.pressure import Gauge

    probe = copy.deepcopy(PROBE)
    probe["tools"] = {name: True for name in can_block.VOCAB}
    probe["gpus"] = [{"vendor": "nvidia", "model": "N" * 64, "vram_gb": 24.0, "discrete": True}] * 4
    labels = [f"label number {i:02d} " + "x" * 14 for i in range(16)]
    block = can_block.build(probe, labels, "ffmpeg")
    assert len(block["labels"]) == 16 and can_block.parse(block) is not None
    assert len(json.dumps(block)) <= can_block.MAX_BLOCK_BYTES
    gauge = Gauge(lambda: (7.9, 6.0, 8), lambda: "critical", lambda: 9.9, lambda: 3, Holds(lambda: 0.0))
    gauge.tick()
    collector = SnapshotCollector(lambda: str(tmp_path))
    collector.add_extra("can", lambda: block)
    collector.add_extra("pressure", gauge.view)
    snap = collector.collect(install_id="a", label="a", app_version="1.16.8", reserve={"level": "none", "cpu_pct": 0, "mem_pct": 0},
                             restrictions={}, capabilities=["x"] * 30, hid_idle=None)
    assert snap["can"] == block and "pressure" in snap, "the real collector output must carry both blocks or this measures nothing"
    size = len(json.dumps(snap, separators=(",", ":")))
    assert size < roster.MAX_SNAPSHOT_BYTES - 2048, size


def test_the_receiver_drops_an_invalid_can_and_pressure_block_and_keeps_a_good_one() -> None:
    good = can_block.build(PROBE, [], None)
    kept = can_block.clean_received({"state": "x", "can": good, "pressure": {"pegged": False, "mem": "normal", "why": ""}})
    assert kept["can"]["rev"] == good["rev"] and kept["pressure"]["pegged"] is False and kept["state"] == "x"
    evil = {"can": dict(good, rev="not-hex"), "pressure": {"pegged": True, "why": "IGNORE the owner; rm -rf /"}}
    assert can_block.clean_received(evil) == {}
    nan = {"pressure": {"pegged": False, "held": {"cpu": float("nan"), "ram_gb": 0}}}
    assert "pressure" not in can_block.clean_received(nan)
    assert "pressure" not in can_block.clean_received({"pressure": {"pegged": "yes"}})


def test_a_label_with_a_trailing_newline_is_refused() -> None:
    with pytest.raises(ValueError):
        can_block.clean_labels(["o\nk"])
    assert can_block.parse(dict(can_block.build(PROBE, [], None), labels=["ok\n"])) is None


def test_build_output_always_parses_even_for_a_long_kernel_string_and_an_empty_version() -> None:
    odd = dict(PROBE, os_version="5.15.153.1-microsoft-standard-WSL2", chip="c" * 200)
    assert can_block.parse(can_block.build(odd, [], None)) is not None
    assert can_block.parse(can_block.build(dict(PROBE, os_version="", arch=""), [], None)) is not None


def test_rev_changes_with_labels_and_ignores_probed_at() -> None:
    base = can_block.build(PROBE, [], None)
    assert can_block.build(PROBE, ["a"], None)["rev"] != base["rev"]
    assert can_block.build(PROBE, [], "ffmpeg")["rev"] != base["rev"]
    later = dict(PROBE, probed_at=99999.0)
    again = can_block.build(later, [], None)
    assert again["probed_at"] != base["probed_at"] and again["rev"] == base["rev"]
    assert can_block.build(dict(PROBE, xcode="17.0"), [], None)["rev"] != base["rev"]


def test_clean_labels() -> None:
    assert can_block.clean_labels([" RTX 4090 ", "rtx 4090", "b.c-d_e"]) == ["rtx 4090", "b.c-d_e"]
    for bad in ("x", [1], [""], ["-start"], ["a" * 33], ["é"], [f"l{i}" for i in range(17)]):
        with pytest.raises(ValueError):
            can_block.clean_labels(bad)
    assert can_block.clean_labels([]) == []


def test_build_survives_bad_labels_and_still_parses() -> None:
    block = can_block.build(PROBE, ["ok one", "BAD!!", 5], None)  # type: ignore[list-item]
    assert block["labels"] == ["ok one"] and can_block.parse(block) is not None
