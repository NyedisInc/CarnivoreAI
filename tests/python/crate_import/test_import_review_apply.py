
from __future__ import annotations

import hashlib
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

from src.core.conversation_writers import SOURCE_PID_RECORD, Writer
from src.core.crate_import import apply as ap
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.crate_import.session_plan import SessionPlan
from src.core.project_move.plan import PaneListing
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_import.install import Install
from tests.python.crate_import.test_import_plan import export_crate, target
from tests.python.crate_import.test_import_same_path import rows_of
from tests.python.inventory.world import CONV_A


def _plan(crate: SimpleNamespace, install: Install) -> dict:
    with cf.open_crate(crate.path) as reader:
        return build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)


def test_an_unrelated_claude_process_does_not_change_the_fingerprint(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    quiet = target(tmp_path, crate, writers=())
    base = _plan(crate, quiet)
    assert base["ok"], base["blockers"]
    busy = replace(quiet, env=replace(quiet.env, writers=lambda: (Writer(4242, "ffffffff-0000-0000-0000-00000000ffff", SOURCE_PID_RECORD, "/elsewhere"),)))
    assert _plan(crate, busy)["fingerprint"] == base["fingerprint"], "a session start or exit elsewhere must not make the apply answer plan_changed"
    mine = replace(quiet, env=replace(quiet.env, writers=lambda: (Writer(4243, CONV_A, SOURCE_PID_RECORD, "/elsewhere"),)))
    assert _plan(crate, mine)["ok"] is False, "a process writing a conversation of the crate still blocks"


def test_the_journal_rebase_names_only_the_sessions_this_import_creates() -> None:
    class Held:
        crate_sessions = [("kept", "c1"), ("attached", "c2"), ("reminted", "c3"), ("left-out", "c4")]
        sessions = SessionPlan(skip_sessions=frozenset({"left-out"}), translate={"attached": "holder", "reminted": "fresh-uuid"},
                               reminted=("reminted",))

    assert ap.imported_uuids(Held()) == ["kept", "fresh-uuid"]  # type: ignore[arg-type]


def test_a_session_that_goes_live_during_the_files_phase_is_not_adopted(tmp_path: Path) -> None:
    crate = export_crate(tmp_path)
    install = target(tmp_path, crate)
    root = crate.world.root1
    with closing(install.db()) as conn:
        conn.execute("INSERT INTO sessions (session_uuid, working_dir, tmux_name, lifecycle, origin, created_at, updated_at) "
                     "VALUES ('local-live', ?, 'carnivore_live1', 'running', 'user', 'now', 'now')", (f"{root}/sub",))
        conn.commit()
    calls: List[int] = []

    def panes() -> PaneListing:
        calls.append(1)
        return PaneListing(True, (("carnivore_live1", None, f"{root}/sub"),) if len(calls) >= 3 else ())

    live = replace(install, env=replace(install.env, panes=panes))
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, live.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)
        assert plan["ok"], plan["blockers"]
        calls.clear()
        ap.apply_import(reader, live.env, ImportRequest(), crate_sha256=crate.sha256, fingerprint=plan["fingerprint"], import_id=new_import_id())
    assert len(calls) >= 3, "the guard must have measured again before the commit"
    row = rows_of(install, "SELECT project_id FROM sessions WHERE session_uuid = 'local-live'")[0]
    assert row["project_id"] is None, "a session that is live when the rows commit is never adopted"
