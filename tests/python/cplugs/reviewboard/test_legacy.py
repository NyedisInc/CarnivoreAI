
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from src.cplugs.reviewboard import legacy
from src.cplugs.reviewboard.cli import convert_legacy
from src.cplugs.reviewboard.scan import scan
from tests.python.cplugs.reviewboard.boards import make_root

NOW = "2026-10-12T22:00:00Z"
VERBATIM = "the state are for movement, if its working, the nudge reaper nudges carnivore  to  keep going\nsecond line"


def _old() -> Dict[str, Any]:
    return {"mockup": "flow.html", "task": "step 0: flowchart", "huddle_item_id": 507, "revision": 3, "created": "2026-10-12",
            "kind": "flowchart-baseline", "source_commit": "f2da01b2d", "model": "flow.model.json",
            "revisions": [{"revision": n, "date": "2026-10-12", "by": "claude", "summary": f"pass {n}"} for n in (1, 2, 3)],
            "notes": [{"date": "2026-10-12", "by": "joe", "stage": "3 movement", "verbatim": VERBATIM, "claude_check": ["matches: t54"]}],
            "choices": [], "views": [{"page": "flow.html", "what": "one picture"}, {"page": "flow-journeys.html", "what": "journeys"}],
            "rulings": [{"date": "2026-10-12", "stage": "3", "rule": "a reply reopens"}], "parked_questions": [{"q": "later?"}]}


def _pages(name: str) -> bytes:
    return {"flow.html": b"<p>main</p>", "flow-journeys.html": b"<p>journeys</p>"}[name]


def _convert(old: Dict[str, Any], item: int = 507) -> legacy.Converted:
    return legacy.convert(old, slug="20261012-flow", item_id=item, computer="mac-mini-m4", viewport=1400, now=NOW, read_page=_pages)


def test_joes_notes_become_rounds_word_for_word_on_the_newest_revision() -> None:
    s = _convert(_old()).sidecar
    (rnd,) = s.rounds
    assert rnd.note == VERBATIM and rnd.revision == "r3" and rnd.by == "joe" and rnd.delivery.item_id == 507
    assert rnd.ext["legacy"].model_dump() == {"v": 1, "date": "2026-10-12", "stage": "3 movement", "claude_check": ["matches: t54"]}
    assert _convert(_old()).sidecar.rounds[0].client_round_id == rnd.client_round_id


def test_older_revisions_point_at_the_kept_pages_and_say_so() -> None:
    converted = _convert(_old())
    s = converted.sidecar
    assert [r.id for r in s.revisions] == ["r1", "r2", "r3"]
    assert ["legacy" in r.ext for r in s.revisions] == [True, True, False]
    assert all(r.ext["legacy"].model_dump() == {"v": 1, "reconstructed": True} for r in s.revisions[:2])
    assert sorted(converted.files) == ["r003--journeys.html", "r003.html"]
    assert [v.file for v in s.revisions[0].views] == ["r003.html", "r003--journeys.html"]
    assert s.revisions[2].source_commit == "f2da01b2d" and s.revisions[0].source_commit is None


def test_everything_the_board_does_not_map_is_kept_under_ext_legacy() -> None:
    kept = _convert(_old()).sidecar.ext["legacy"].model_dump()
    assert kept["rulings"] == _old()["rulings"] and kept["parked_questions"] == [{"q": "later?"}]
    assert kept["model"] == "flow.model.json" and kept["kind"] == "flowchart-baseline" and kept["huddle_item_id"] == 507


def test_a_stated_item_that_differs_from_the_old_file_is_a_history_line() -> None:
    corrected = _convert(_old(), item=517).sidecar.task
    assert corrected.item_id == 517 and len(corrected.history) == 1
    line = corrected.history[0]
    assert (line.from_item_id, line.item_id, line.at, line.by) == (507, 517, NOW, legacy.CONVERTER)
    assert _convert(_old()).sidecar.task.history == []


@pytest.mark.parametrize("change, message", [
    ({"choices": [{"id": "x"}]}, "has choices"),
    ({"revision": 4}, "do not run 1, 2"),
    ({"notes": [{"by": "joe", "date": "2026-10-12"}]}, "no verbatim"),
    ({"notes": [{"by": "joe", "date": "2026-10-12", "verbatim": "x" * 8001}]}, "8000"),
    ({"mockup": None}, "names no mockup"),
])
def test_what_cannot_be_mapped_without_guessing_is_refused(change: Dict[str, Any], message: str) -> None:
    old = _old()
    old.update(change)
    with pytest.raises(ValueError, match=message):
        _convert(old)


def _cli(tmp_path: Path, board: Path, *extra: str) -> tuple:
    old_dir = tmp_path / "old"
    old_dir.mkdir(exist_ok=True)
    (old_dir / "flow.sidecar.json").write_text(json.dumps(_old()))
    for name in ("flow.html", "flow-journeys.html"):
        (old_dir / name).write_bytes(_pages(name))
    out = io.StringIO()
    code = convert_legacy.main([str(old_dir / "flow.sidecar.json"), str(board), "--item", "507", "--computer", "mac-mini-m4",
                                "--viewport", "1400", *extra], out=out, now=NOW)
    return code, out.getvalue()


def test_the_command_line_dry_runs_writes_once_and_never_overwrites(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    board = root / "20261012-flow"
    code, text = _cli(tmp_path, board)
    assert code == 0 and "dry run" in text and not board.exists()
    code, text = _cli(tmp_path, board, "--write")
    assert code == 0 and "wrote" in text
    assert scan(root).exit_code == 0 and scan(root).findings == ()
    assert not list(root.glob(".*.converting"))
    before = (board / "sidecar.json").read_bytes()
    code, text = _cli(tmp_path, board, "--write")
    assert code == 1 and "already exists" in text and (board / "sidecar.json").read_bytes() == before


def test_the_command_line_writes_only_into_a_marked_boards_folder(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    code, text = _cli(tmp_path, plain / "20261012-flow", "--write")
    assert code == 1 and "not a boards folder" in text and not (plain / "20261012-flow").exists()
