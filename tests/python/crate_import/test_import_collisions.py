
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.core.crate_import import apply as ap
from src.core.crate_import import files_place, hooks as hk
from src.core.crate_import.model import ImportRefused, ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.project_move.plan import PaneListing
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_import.install import Install
from tests.python.crate_import.test_import_plan import codes
from tests.python.crate_import.test_import_same_path import Faults, rows_of, run, seeded, world
from tests.python.inventory.world import CONV_A, CONV_B, UUID_A, UUID_B
from tests.python.session_purge.purge_world import add_session, insert


def enc_of(crate: SimpleNamespace, conversation: str) -> str:
    with cf.open_crate(crate.path) as reader:
        return next(c.enc_folder for c in reader.manifest.conversations if c.id == conversation)


def source_file(crate: SimpleNamespace, conversation: str) -> Path:
    return Path(crate.world.home) / "projects" / enc_of(crate, conversation) / f"{conversation}.jsonl"


def local_file(install: Install, crate: SimpleNamespace, conversation: str) -> Path:
    return install.claude / "projects" / enc_of(crate, conversation) / f"{conversation}.jsonl"


def put_local(install: Install, crate: SimpleNamespace, conversation: str, data: bytes) -> Path:
    path = local_file(install, crate, conversation)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def plan_of(crate: SimpleNamespace, install: Install, request: ImportRequest) -> dict:
    with cf.open_crate(crate.path) as reader:
        return build_plan(reader, install.env, request, crate_sha256=crate.sha256, encrypted=False)


def uuids(install: Install) -> List[str]:
    return sorted(r["session_uuid"] for r in rows_of(install, "SELECT session_uuid FROM sessions"))


def test_a_busy_install_gets_new_ids_and_every_derived_key_follows(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    with closing(install.db()) as conn:
        other = insert(conn, "projects", uid="other-uid", display_name="Other", root=str(install.projects / "other"),
                       raw_path=str(install.projects / "other"), source="user", created_at="now", updated_at="now")
        for n in range(3):
            add_session(conn, f"local-uuid-{n}", f"carnivore_local_{n}", f"local-conv-{n}")
        insert(conn, "session_groups", group_uuid="g-local", name="local", position=0, created_at="now", updated_at="now")
        insert(conn, "layouts", layout_uuid="l-local", name="local", name_fold="local", position=0, shape="x", revision=1,
               created_at="now", updated_at="now")
        conn.commit()
    receipt = run(crate, install)
    assert receipt.state in ("done", "done_with_warnings")
    sessions = {r["session_uuid"]: r["id"] for r in rows_of(install, "SELECT id, session_uuid FROM sessions")}
    assert sessions[UUID_A] > 3 and sessions[UUID_B] > 3 and len(sessions) == 5
    project = rows_of(install, "SELECT id FROM projects WHERE uid = 'project-uid-1'")[0]["id"]
    assert project != other
    assert {r["project_id"] for r in rows_of(install, "SELECT project_id FROM sessions WHERE session_uuid IN (?, ?)", UUID_A, UUID_B)} == {project}
    assert [r["layout_uuid"] for r in rows_of(install, "SELECT layout_uuid FROM layouts ORDER BY id")] == ["l-local", "l-1"]
    members = rows_of(install, "SELECT s.session_uuid FROM layout_members m JOIN layouts l ON l.id = m.layout_id "
                               "JOIN sessions s ON s.id = m.session_row_id WHERE l.layout_uuid = 'l-1'")
    assert [m["session_uuid"] for m in members] == [UUID_A]
    grouped = rows_of(install, "SELECT s.session_uuid FROM session_group_membership m JOIN session_groups g ON g.id = m.group_id "
                               "JOIN sessions s ON s.session_uuid = m.session_uuid WHERE g.group_uuid = 'g-1'")
    assert [g["session_uuid"] for g in grouped] == [UUID_A]
    assert rows_of(install, "SELECT parent_session_id FROM sessions WHERE session_uuid = ?", UUID_B)[0]["parent_session_id"] == sessions[UUID_A]


def test_a_natural_key_row_here_wins_and_is_listed(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    with closing(install.db()) as conn:
        insert(conn, "conversation_index", conversation_id=CONV_B, session_uuid=UUID_B, captured_at="local stamp", updated_at="now")
        conn.commit()
    plan = plan_of(crate, install, ImportRequest())
    assert plan["ok"], plan["blockers"]
    assert plan["rows"]["cloude.db.conversation_index"]["kept_local"] == 1
    receipt = run(crate, install)
    assert receipt.rows["cloude.db.conversation_index"]["kept_local"] == 1
    assert rows_of(install, "SELECT captured_at FROM conversation_index WHERE conversation_id = ?", CONV_B)[0]["captured_at"] == "local stamp"


def test_a_shorter_local_transcript_grows_with_a_backup(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    full = source_file(crate, CONV_A).read_bytes()
    path = put_local(install, crate, CONV_A, full[: len(full) // 2])
    plan = plan_of(crate, install, ImportRequest())
    assert plan["ok"], plan["blockers"]
    assert {c["id"]: c["class"] for c in plan["conversations"]}[CONV_A] == "grow"
    receipt = run(crate, install)
    assert path.read_bytes() == full and receipt.checks["file_mismatch"] == []
    backups = [p for p in install.env.state.rglob("*") if p.is_file() and p.read_bytes() == full[: len(full) // 2] and "backups" in p.parts]
    assert len(backups) == 1 and receipt.import_id in backups[0].parts
    assert {c["id"]: c["class"] for c in receipt.conversations}[CONV_A] == "grow"


@pytest.mark.parametrize("at", [hk.CP_AFTER_FILES, hk.CP_BEFORE_COMMIT])
def test_a_fault_after_a_grow_puts_the_local_bytes_back(tmp_path: Path, at: str) -> None:
    crate, install = seeded(tmp_path)
    full = source_file(crate, CONV_A).read_bytes()
    path = put_local(install, crate, CONV_A, full[: len(full) // 2])
    before = world(install)
    hooks = Faults(at, RuntimeError("injected"))
    with pytest.raises(RuntimeError, match="injected"):
        run(crate, install, hooks)
    assert any(e["op"] == "grow" for e in hooks.log)
    assert path.read_bytes() == full[: len(full) // 2]
    assert world(install) == before


def test_a_grow_is_not_done_over_a_file_someone_changed_after_the_preview(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    full = source_file(crate, CONV_A).read_bytes()
    path = put_local(install, crate, CONV_A, full[: len(full) // 2])

    class Edits(hk.ApplyHooks):
        def checkpoint(self, name: str) -> None:
            if name == hk.CP_BEFORE_FILES:
                path.write_bytes(b"someone typed here\n")

    before = world(install)
    with pytest.raises(Exception) as caught:
        run(crate, install, Edits())
    assert getattr(caught.value, "code", "") in ("plan_changed", "destination_changed"), caught.value
    assert path.read_bytes() == b"someone typed here\n"
    assert world(install)[0] == before[0]


def test_a_different_transcript_refuses_its_session_and_skip_conflicts_lists_it(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    path = put_local(install, crate, CONV_B, b"something else entirely\n")
    plan = plan_of(crate, install, ImportRequest())
    assert plan["ok"] is False and "conversation_owned_elsewhere" not in codes(plan["blockers"])
    assert any(b["detail"] == CONV_B for b in plan["blockers"])
    with cf.open_crate(crate.path) as reader, pytest.raises(ImportRefused) as refused:
        ap.apply_import(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, fingerprint=plan["fingerprint"], import_id=new_import_id())
    assert refused.value.code == "blocked"
    skipping = ImportRequest(skip_conflicts=True)
    assert plan_of(crate, install, skipping)["ok"] is True
    receipt = run(crate, install, request=skipping)
    assert path.read_bytes() == b"something else entirely\n"
    assert uuids(install) == [UUID_A]
    assert {c["id"]: c["class"] for c in receipt.conversations}[CONV_B] == "excluded"
    assert rows_of(install, "SELECT COUNT(*) AS n FROM conversation_index WHERE conversation_id = ?", CONV_B)[0]["n"] == 0
    assert rows_of(install, "SELECT COUNT(*) AS n FROM conversation_index WHERE conversation_id = ?", CONV_A)[0]["n"] == 1
    assert receipt.rows["cloude.db.sessions"]["inserted"] == 1


def test_a_session_uuid_here_with_another_conversation_is_reminted_and_its_children_follow(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    with closing(install.db()) as conn:
        add_session(conn, UUID_A, "carnivore_local_a", "some-other-conversation-0001")
        conn.commit()
    plan = plan_of(crate, install, ImportRequest())
    assert plan["ok"], plan["blockers"]
    assert "session_uuid_reminted" in codes(plan["warnings"])
    assert plan_of(crate, install, ImportRequest())["fingerprint"] == plan["fingerprint"]
    run(crate, install)
    mine = rows_of(install, "SELECT session_uuid FROM sessions WHERE claude_session_uuid = ?", CONV_A)
    assert len(mine) == 1 and mine[0]["session_uuid"] != UUID_A
    new = mine[0]["session_uuid"]
    assert rows_of(install, "SELECT claude_session_uuid FROM sessions WHERE session_uuid = ?", UUID_A)[0]["claude_session_uuid"] == "some-other-conversation-0001"
    assert rows_of(install, "SELECT COUNT(*) AS n FROM session_notes WHERE session_uuid = ?", new)[0]["n"] == 1
    assert rows_of(install, "SELECT COUNT(*) AS n FROM session_notes WHERE session_uuid = ?", UUID_A)[0]["n"] == 0
    assert rows_of(install, "SELECT session_uuid FROM conversation_index WHERE conversation_id = ?", CONV_A)[0]["session_uuid"] == new
    again = run(crate, install)
    assert again.state == "noop" and len(uuids(install)) == 3


def test_a_conversation_another_row_holds_is_not_duplicated(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    put_local(install, crate, CONV_B, source_file(crate, CONV_B).read_bytes())
    with closing(install.db()) as conn:
        add_session(conn, "holder-uuid", "carnivore_holder", CONV_B)
        conn.commit()
    plan = plan_of(crate, install, ImportRequest())
    assert plan["ok"], plan["blockers"]
    run(crate, install)
    assert sorted(uuids(install)) == sorted([UUID_A, "holder-uuid"])
    assert rows_of(install, "SELECT session_uuid FROM conversation_index WHERE conversation_id = ?", CONV_B)[0]["session_uuid"] == "holder-uuid"


def test_a_cloud_only_local_file_is_a_conflict_and_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    crate, install = seeded(tmp_path)
    path = put_local(install, crate, CONV_B, b"placeholder\n")
    monkeypatch.setattr(files_place, "is_dataless_file", lambda p: Path(p) == path)
    reads: List[Any] = []
    monkeypatch.setattr(files_place, "sha256_file", lambda p: reads.append(p) or "x")
    plan = plan_of(crate, install, ImportRequest())
    assert plan["ok"] is False and "local_cloud_only" in codes(plan["warnings"])
    assert path not in [Path(r) for r in reads]
    assert {c["id"]: c["class"] for c in plan["conversations"]}[CONV_B] == "conflict"


def test_a_live_loose_session_under_the_new_root_is_not_adopted(tmp_path: Path) -> None:
    crate, install = seeded(tmp_path)
    root = crate.world.root1
    with closing(install.db()) as conn:
        for name, epoch in (("carnivore_live", 5), ("carnivore_idle", 6)):
            row = add_session(conn, f"loose-{name}", name, f"loose-conv-{name}", epoch=epoch)
            conn.execute("UPDATE sessions SET working_dir = ?, project_id = NULL, lifecycle = 'running' WHERE id = ?", (f"{root}/sub", row))
        conn.commit()
    install.env = replace(install.env, panes=lambda: PaneListing(True, (("carnivore_live", 5, root),)))
    plan = plan_of(crate, install, ImportRequest())
    assert plan["ok"], plan["blockers"]
    assert [a["session_id"] for a in plan["project"]["adoptions"]] != [] and len(plan["project"]["adoptions"]) == 1
    assert "adoption" in codes(plan["warnings"])
    run(crate, install)
    projects = {r["session_uuid"]: r["project_id"] for r in rows_of(install, "SELECT session_uuid, project_id FROM sessions")}
    assert projects["loose-carnivore_live"] is None
    assert projects["loose-carnivore_idle"] == projects[UUID_A]


def test_a_writer_that_appears_after_the_preview_stops_the_apply_before_any_file_is_touched(tmp_path: Path) -> None:
    from src.core.conversation_writers import Writer

    crate, install = seeded(tmp_path)
    full = source_file(crate, CONV_A).read_bytes()
    path = put_local(install, crate, CONV_A, full[: len(full) // 2])
    appeared: List[Writer] = []
    install.env = replace(install.env, writers=lambda: tuple(appeared))

    class Opens(hk.ApplyHooks):
        logged: List[Any] = []

        def undo(self, entry: Any) -> None:
            self.logged.append(entry)

        def checkpoint(self, name: str) -> None:
            if name == hk.CP_BEFORE_FILES:
                appeared.append(Writer(4242, CONV_A, "argv_resume"))

    before = world(install)
    with pytest.raises(ImportRefused) as caught:
        run(crate, install, Opens())
    assert caught.value.code == "conversation_live" and Opens.logged == []
    assert path.read_bytes() == full[: len(full) // 2] and world(install) == before
