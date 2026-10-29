
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.contrast import pairings, run_mutation_check as rmc


def _mutation(path: Path, apply=None) -> rmc.Mutation:
    return rmc.Mutation("m", path, apply or (lambda p: p.write_text("MUTANT", encoding="utf-8")))


def test_the_file_is_restored_when_the_runner_raises(tmp_path: Path) -> None:
    target = tmp_path / "f.css"
    target.write_text("original")

    def boom() -> bool:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        rmc.run_mutation(_mutation(target), boom)
    assert target.read_text() == "original"


def test_killed_and_survived(tmp_path: Path) -> None:
    target = tmp_path / "f.css"
    target.write_text("x")
    assert rmc.run_mutation(_mutation(target), lambda: False) == rmc.KILLED
    assert rmc.run_mutation(_mutation(target), lambda: True) == rmc.SURVIVED
    assert target.read_text() == "x"


def test_a_stale_anchor_is_cannot_determine_not_an_assert(tmp_path: Path) -> None:
    target = tmp_path / "f.css"
    target.write_text("no anchor here")
    mutation = _mutation(target, lambda p: rmc._replace_once(p, "missing", "x"))
    assert rmc.run_mutation(mutation, lambda: False) == rmc.CANNOT_DETERMINE
    assert target.read_text() == "no anchor here"


def test_a_red_baseline_is_exit_2_and_nothing_is_mutated(tmp_path: Path) -> None:
    target = tmp_path / "f.css"
    target.write_text("x")
    assert rmc.main(tests_pass=lambda: False, mutations=[_mutation(target)]) == 2
    assert target.read_text() == "x"


def test_a_survivor_is_exit_1(tmp_path: Path) -> None:
    target = tmp_path / "f.css"
    target.write_text("x")
    assert rmc.main(tests_pass=lambda: True, mutations=[_mutation(target)]) == 1


def test_the_real_mutations_have_live_anchors() -> None:
    for mutation in rmc.build_mutations():
        before = mutation.path.read_text(encoding="utf-8")
        mutation.apply(mutation.path)
        mutation.path.write_text(before, encoding="utf-8")


def test_no_pairing_cites_the_removed_stripe() -> None:
    assert not [p for p in pairings.PAIRINGS if "stripe" in p.name]
