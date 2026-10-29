
from __future__ import annotations

import asyncio
import json
import os
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from src.config import settings
from src.core.approvals.carried_trust import IMPORTS_YES_LABEL
from tests.python.approvals.auto_helpers import make_engine
from src.core.approvals.extract import extract_dialog
from src.core.pack.identity import replicas
from src.core.pack.trust_carry import imports, store
from tests.python.pack.test_migrate_two_machines import world  # noqa: F401

SCREEN = (Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens" / "external_imports.txt").read_text()


def _project(tmp_path: Path, memory: str = "") -> str:
    folder = tmp_path / "src-proj"
    folder.mkdir()
    if memory:
        (folder / "CLAUDE.md").write_text(memory)
    return str(folder)


def _profile(tmp_path: Path, name: str, folder: str, approved: bool) -> str:
    prof = tmp_path / name
    prof.mkdir()
    (prof / ".claude.json").write_text(json.dumps({"projects": {folder: {imports.APPROVED_KEY: approved}}}))
    return str(prof)


def _presses(conn_of, folder: str, screen: str = SCREEN) -> list:
    sent = []

    async def answer(sid, fingerprint, label):
        sent.append(label)

    async def info(_sid):
        return SimpleNamespace(session=SimpleNamespace(working_dir=folder), agent_family="claude", startup_gate="awaiting_startup_prompt")

    def _carried(conn_of, path):
        with closing(conn_of()) as conn:
            return store.carried_op(conn, path)

    def lookup_imports(path):
        with closing(conn_of()) as conn:
            return store.carried_imports_ok(conn, path)

    obs = SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=extract_dialog(screen, "claude"), identity=("s", "n", 1, 9)))

    async def run():
        ack = make_engine(answer=answer, info=info, lookup_imports=lookup_imports, lookup=lambda path: _carried(conn_of, path))
        task = ack.on_observation(SimpleNamespace(session_id="ses_1"), obs)
        if task is not None:
            await task

    asyncio.run(run())
    return sent


def test_a_project_with_no_outside_import_is_settled_on_the_target(world, monkeypatch, tmp_path) -> None:
    a, b, current, link = world
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: b.projects, raising=True)
    inside = _project(tmp_path, "see @docs/rules.md and `@/not/an/import` and bob@example.com\n```\n@/fenced/outside.md\n```\n")
    (Path(inside) / "docs").mkdir()
    (Path(inside) / "docs" / "rules.md").write_text("plain\n")
    assert imports.own_files_import_outside(inside) is False
    monkeypatch.setattr(imports, "claude_json_path", lambda: tmp_path / "none.json")
    ok = imports.source_imports_ok(inside, [None])
    assert ok is True
    with closing(b.conn()) as conn:
        replicas.accept_replica(conn, home_install_id="iid-a", project_uid="a0f1" * 8, name="fresh", root=str(b.projects / "fresh"),
                                source_trusted=True, source_imports_ok=ok)
    assert _presses(b.conn, os.path.realpath(b.projects / "fresh")) == [IMPORTS_YES_LABEL]


def test_an_outside_import_is_carried_only_when_every_source_profile_approved(world, monkeypatch, tmp_path) -> None:
    a, b, current, link = world
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: b.projects, raising=True)
    folder = _project(tmp_path, "@/Users/someone/skill/SKILL.md\n")
    assert imports.own_files_import_outside(folder) is True
    yes1, yes2 = _profile(tmp_path, "p1", folder, True), _profile(tmp_path, "p2", folder, True)
    no = _profile(tmp_path, "p3", folder, False)
    assert imports.source_imports_ok(folder, [yes1, yes2]) is True
    assert imports.source_imports_ok(folder, [yes1, no]) is False
    assert imports.source_imports_ok(folder, [yes1, ""]) is False
    assert imports.source_imports_ok(folder, [str(tmp_path / "missing")]) is False
    for name, ok in (("approved", True), ("refused", False)):
        with closing(b.conn()) as conn:
            replicas.accept_replica(conn, home_install_id="iid-a", project_uid=("b0f1" if ok else "c0f1") * 8, name=name,
                                    root=str(b.projects / name), source_trusted=True, source_imports_ok=imports.source_imports_ok(folder, [yes1] if ok else [no]))
        assert _presses(b.conn, os.path.realpath(b.projects / name)) == ([IMPORTS_YES_LABEL] if ok else [])


def test_a_symlinked_memory_file_that_leaves_the_folder_is_an_outside_import(tmp_path) -> None:
    outside = tmp_path / "elsewhere.md"
    outside.write_text("x\n")
    folder = Path(_project(tmp_path))
    (folder / "CLAUDE.local.md").symlink_to(outside)
    assert imports.own_files_import_outside(str(folder)) is True


def test_a_pre_existing_target_folder_gets_nothing(world, monkeypatch, tmp_path) -> None:
    a, b, current, link = world
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: b.projects, raising=True)
    (b.projects / "existing").mkdir()
    with closing(b.conn()) as conn:
        replicas.accept_replica(conn, home_install_id="iid-a", project_uid="d0f1" * 8, name="existing", root=str(b.projects / "existing"),
                                source_trusted=True, source_imports_ok=True)
        assert store.carried_imports_ok(conn, os.path.realpath(b.projects / "existing")) is False
    assert _presses(b.conn, os.path.realpath(b.projects / "existing")) == []
