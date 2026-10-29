
from __future__ import annotations

from pathlib import Path

from tests.python.cplugs.removability import assert_no_dangling_assets, run_cycle


def test_the_cycle_leaves_no_residue(tmp_path: Path) -> None:
    run_cycle("timemachine", tmp_path)


def test_deleting_its_folders_leaves_nothing_dangling() -> None:
    assert_no_dangling_assets("timemachine")
