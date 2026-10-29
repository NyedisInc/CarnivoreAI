from __future__ import annotations

import json

import pytest

from scripts.contrast.color_utils import ColorResolutionError
from scripts.contrast.roles import BASELINE, bundled, compare, failing, matrix

THEMES = bundled()


def _found() -> dict[str, dict[str, float]]:
    out = {}
    for tid, table in THEMES.items():
        try:
            out[tid] = failing(table)
        except ColorResolutionError as err:
            pytest.fail(f"{tid}: could not resolve a role color: {err}")
    return out


def test_every_bundled_theme_is_measured() -> None:
    assert len(THEMES) >= 12
    assert all(len(matrix(table)) == 49 for table in THEMES.values())


def test_report(capsys: pytest.CaptureFixture[str]) -> None:
    found = _found()
    with capsys.disabled():
        print("\nrole contrast, pairs below minimum per bundled theme:")
        for tid, pairs in found.items():
            print(f"  {tid:16} {len(pairs):2}  " + ", ".join(f"{p} {r:.2f}" for p, r in sorted(pairs.items())))
    assert sum(len(p) for p in found.values()) < len(THEMES) * 49


def test_no_theme_got_worse() -> None:
    worse, _ = compare(_found(), json.loads(BASELINE.read_text(encoding="utf-8"))["themes"])
    assert not worse, "role contrast got worse:\n  " + "\n  ".join(worse)


def test_baseline_is_not_stale() -> None:
    _, stale = compare(_found(), json.loads(BASELINE.read_text(encoding="utf-8"))["themes"])
    assert not stale, "record the improvement (--write-baseline):\n  " + "\n  ".join(stale)


def test_negative_control_a_dimmed_ink_goes_red() -> None:
    tid = "carnivore"
    planted = {**THEMES[tid], "color-fg-faint": "#3a3f42"}
    worse, _ = compare({tid: failing(planted)}, {tid: _found()[tid]})
    assert any(line.startswith(f"{tid}: faint on base") for line in worse), worse


def test_negative_control_a_lower_ratio_on_a_known_pair_goes_red() -> None:
    worse, _ = compare({"t": {"faint on overlay": 3.5}}, {"t": {"faint on overlay": 3.86}})
    assert worse == ["t: faint on overlay fell from 3.86 to 3.50"]
