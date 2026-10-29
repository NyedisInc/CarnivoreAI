
from __future__ import annotations

import asyncio
import hashlib
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from src.api import recreate_action, recreate_routes
from src.core.crate_import import fork_marker
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_import import apply as ap
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.db import connect, db_path_for, get_meta
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_import.install import Install, make_install
from tests.python.crate_import.test_import_same_path import rows_of

SHARE = Path(__file__).resolve().parents[2] / "fixtures" / "crate" / "v1" / "project-share.crate"
SENDER_UUIDS = {"sess-uuid-A-0001", "sess-uuid-B-0002"}


def restore_share(install: Install, request: ImportRequest) -> tuple:
    sha = hashlib.sha256(SHARE.read_bytes()).hexdigest()
    with cf.open_crate(SHARE) as reader:
        plan = build_plan(reader, install.env, request, crate_sha256=sha, encrypted=False)
        assert plan["ok"], plan["blockers"]
        receipt = ap.apply_import(reader, install.env, request, crate_sha256=sha, fingerprint=plan["fingerprint"], import_id=new_import_id())
    return plan, receipt


def share_request(install: Install) -> ImportRequest:
    return ImportRequest(mode="relocate", new_root=str(install.projects / "shared-in"))


def test_a_share_crate_plans_as_foreign_with_its_files_in_the_new_roots_folder(tmp_path: Path) -> None:
    install = make_install(tmp_path)
    sha = hashlib.sha256(SHARE.read_bytes()).hexdigest()
    with cf.open_crate(SHARE) as reader:
        plan = build_plan(reader, install.env, share_request(install), crate_sha256=sha, encrypted=False)
    assert plan["ok"], plan["blockers"]
    assert (plan["provenance"], plan["provenance_reason"]) == ("foreign", "share_crate")
    root = plan["project"]["root_to"]
    assert [e["to"] for e in plan["enc"]] == [slugify_project_dir(root)] and plan["enc"][0]["from"] == "_shared"
    assert len(plan["sessions"]["share"]) == 2 and not SENDER_UUIDS & set(plan["sessions"]["share"])


def test_a_share_restore_places_the_files_and_wakes_asleep_sessions_that_fork(tmp_path: Path) -> None:
    install = make_install(tmp_path)
    plan, receipt = restore_share(install, share_request(install))
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    root = plan["project"]["root_to"]

    folder = install.claude / "projects" / slugify_project_dir(root)
    assert not (install.claude / "projects" / "_shared").exists()
    with cf.open_crate(SHARE) as reader:
        main = [f for f in reader.files() if f.role == "transcript"]
        assert main
        for record in main:
            placed = folder / Path(record.rel).name
            assert hashlib.sha256(placed.read_bytes()).hexdigest() == record.content_sha256

    sessions = rows_of(install, "SELECT * FROM sessions ORDER BY session_uuid")
    assert [s["session_uuid"] for s in sessions] == sorted(plan["sessions"]["share"])
    assert not SENDER_UUIDS & {s["session_uuid"] for s in sessions}
    assert {(s["lifecycle"], s["tmux_name"], s["origin"], s["working_dir"]) for s in sessions} == {("stopped", None, "imported", root)}
    assert {s["claude_session_uuid"] for s in sessions} == {"aaaaaaaa-0000-0000-0000-0000000000a0", "bbbbbbbb-0000-0000-0000-00000000000b"}
    project = rows_of(install, "SELECT id, root FROM projects")[0]
    assert {s["project_id"] for s in sessions} == {project["id"]} and project["root"] == root

    with closing(connect(db_path_for(install.state), create=False)) as conn:
        for session in sessions:
            assert get_meta(conn, fork_marker.marker_key(session["session_uuid"])) == session["claude_session_uuid"]


def test_a_second_run_writes_nothing(tmp_path: Path) -> None:
    install = make_install(tmp_path)
    restore_share(install, share_request(install))
    before = rows_of(install, "SELECT session_uuid, updated_at FROM sessions ORDER BY session_uuid")
    _plan, again = restore_share(install, share_request(install))
    assert again.state == "noop"
    assert [tuple(r) for r in rows_of(install, "SELECT session_uuid, updated_at FROM sessions ORDER BY session_uuid")] == [tuple(r) for r in before]


def test_the_marker_holds_until_the_conversation_id_changes(tmp_path: Path) -> None:
    install = make_install(tmp_path)
    with closing(install.db()) as conn:
        fork_marker.set_marker(conn, "s-1", "conv-1")
        conn.commit()
    path = db_path_for(install.state)
    assert fork_marker.wake_forks_at(path, "s-1", "conv-1") is True
    assert fork_marker.wake_forks_at(path, "s-1", "conv-1") is True, "a wake that did not correlate a new id forks again"
    assert fork_marker.wake_forks_at(path, "s-1", "conv-2") is False, "the fork got its own id: the marker is stale"
    with closing(connect(path, create=False)) as conn:
        assert get_meta(conn, fork_marker.marker_key("s-1")) is None
    assert fork_marker.wake_forks_at(path, "other", "conv-1") is False


def test_recreate_adds_fork_session_from_the_marker_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = make_install(tmp_path)
    with closing(install.db()) as conn:
        fork_marker.set_marker(conn, "s-1", "conv-1")
        conn.commit()
    monkeypatch.setattr(recreate_routes, "_db_path", lambda: db_path_for(install.state))
    seen: List[Any] = []

    async def no_hold(_uuid: str) -> None:
        return None

    async def active(_dir: Any) -> None:
        return None

    def gather(uuid: str, overrides: Any, **_kw: Any) -> Dict[str, Any]:
        row = {"session_uuid": uuid, "claude_session_uuid": "conv-1", "working_dir": "/x"}
        return {"row": row, "name": "n", "presence": None, "extra_args": ["--resume", "conv-1"], "directory": type("D", (), {"refuses": False})()}

    def stop(_settings: Any, _agent: Any, **kw: Any) -> None:
        seen.append(kw["extra_args"])
        raise HTTPException(status_code=418, detail="captured")

    monkeypatch.setattr("src.api.swarm_switch_routes.refuse_held_body", no_hold)
    monkeypatch.setattr(recreate_action.project_home, "require_active", active)
    monkeypatch.setattr(recreate_routes, "_gather", gather)
    monkeypatch.setattr(recreate_routes, "validate_agent_choice", stop)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(recreate_action.recreate_by_uuid("s-1", "claude", get_manager=lambda: None))
    assert caught.value.status_code == 418 and seen == [["--resume", "conv-1", "--fork-session"]]
    with closing(connect(db_path_for(install.state), create=False)) as conn:
        assert get_meta(conn, fork_marker.marker_key("plain")) is None
