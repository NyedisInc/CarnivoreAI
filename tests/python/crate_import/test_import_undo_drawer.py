
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Dict

from src.core import config_writer, ui_preferences
from src.core.crate_import import entries_in, ledger, undo_import
from src.core.db import connect, db_path_for
from tests.python.crate_import.test_import_work_side import export_world, run, target_install


def arrangement(install: Any) -> Dict[str, Any]:
    return ui_preferences.read_block(config_writer.read_config(install.env.config_path))["values"].get(entries_in.ARRANGEMENT)


def seed(install: Any, value: Dict[str, Any]) -> None:
    config_writer.commit(install.env.config_path, lambda c: ui_preferences.apply_changes(c, ui_preferences.validate_changes({entries_in.ARRANGEMENT: value}))[0])


def undo_drawer(install: Any, receipt: Any) -> int:
    with closing(connect(db_path_for(install.state), create=False)) as conn:
        record = ledger.read_undo(conn, receipt.import_id)
    out = undo_import.undo_entries(install.env, record["entries"], record.get("journal"))
    return int(out[0].split(" ")[0]) if out else 0


def check(tmp: Path, before: Dict[str, Any]) -> None:
    crate = export_world(tmp)
    install = target_install(tmp, crate)
    if before:
        seed(install, before)
    pre = arrangement(install)
    receipt = run(crate, install)
    after = arrangement(install)
    assert after != pre and after["mobile"]["collapsed"], "the import must have added phone folds"
    reported = undo_drawer(install, receipt)
    now = arrangement(install)
    if pre is None:
        assert not any(now.get(k) for k in ("pinned", "order", "collapsed", "mobile", "bands")), now
    else:
        assert now == pre
    assert reported == receipt.entries["drawer_members"]


def test_undo_restores_the_arrangement_when_there_was_none_before(tmp_path: Path) -> None:
    check(tmp_path, {})


def test_undo_restores_the_arrangement_when_the_phone_had_its_own_folds(tmp_path: Path) -> None:
    check(tmp_path, {"v": 1, "pinned": ["keep"], "order": ["keep"], "collapsed": ["layouts"], "mobile": {"collapsed": ["layouts"]}})


def test_undo_restores_the_arrangement_when_the_phone_had_no_view(tmp_path: Path) -> None:
    check(tmp_path, {"v": 1, "pinned": ["keep"], "order": ["keep"], "collapsed": ["layouts"]})
