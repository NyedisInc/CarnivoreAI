
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.core.crate_import import apply as ap
from src.core.crate_import import hooks as hk
from src.core.crate_import.model import new_import_id
from tests.python.crate_import.test_import_boards import SLUG_MINE, SLUG_NESTED, board_raw, export_rig, wired
from tests.python.cplugs.reviewboard.boards import make_board
from tests.python.crate_import.test_import_same_path import run


class RecordingHooks(hk.ApplyHooks):

    def __init__(self) -> None:
        self.log: List[Dict[str, Any]] = []

    def undo(self, entry: Dict[str, Any]) -> None:
        self.log.append(entry)


def test_undo_removes_the_boards_an_import_wrote_and_keeps_the_one_that_was_here(tmp_path: Path) -> None:
    crate = export_rig(tmp_path)
    install, homes, _calls = wired(tmp_path, crate)
    root = homes["boards"]
    local = board_raw(SLUG_MINE, None)
    local["board"]["title"] = "a local board with the crate's slug"
    make_board(root, local)
    kept_bytes = (root / SLUG_MINE / "sidecar.json").read_bytes()
    hooks, import_id = RecordingHooks(), new_import_id()
    receipt = run(crate, install, hooks=hooks, import_id=import_id)
    states = {b["slug"]: b["state"] for b in receipt.plugin_data["boards"]}
    assert states == {SLUG_MINE: "beside", SLUG_NESTED: "place"}
    placed = Path(next(b["path"] for b in receipt.plugin_data["boards"] if b["slug"] == SLUG_NESTED))
    beside = root / ".crate-import" / import_id
    assert (placed / "sidecar.json").is_file() and beside.is_dir()

    report = ap.recover_files(hooks.log, install.env, import_id)

    assert not placed.exists(), "the board this import placed is removed (its relinked sidecar included)"
    assert not (beside / "boards" / SLUG_MINE).exists(), "the crate copy beside the local board is removed"
    assert (root / SLUG_MINE / "sidecar.json").read_bytes() == kept_bytes, "the board that was here is untouched"
    assert str(root / SLUG_MINE / "sidecar.json") not in report.removed + report.kept
    assert not report.errors and not report.kept, report
