
from __future__ import annotations

from pathlib import Path

from src.cplugs.reviewboard.cli.scan import render
from src.cplugs.reviewboard.scan import scan

ROOT = Path(__file__).resolve().parents[4]
BOARDS = ROOT / "design" / "boards"


def test_every_committed_board_scans_clean() -> None:
    result = scan(BOARDS)
    assert result.exit_code == 0 and result.findings == (), render(result)
    assert {"20261012-current-flow", "20261012-target-flow"} <= {b.slug for b in result.boards}
    assert all(b.status == "ok" for b in result.boards)
