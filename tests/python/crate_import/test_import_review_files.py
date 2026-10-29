
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_format.model_files import FileRecord
from src.core.crate_import import files_place
from src.core.crate_import.enc import EncEntry
from src.core.crate_import.model import ImportRequest
from src.core.crate_import.plan import build_plan
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_import.test_import_plan import tree_hash  # noqa: F401
from tests.python.crate_import.test_import_same_path import run
from tests.python.crate_import.test_import_work_side import export_world, target_install
from tests.python.inventory.world import CONV_A, UUID_A


def _with_profile(install, tmp: Path):  # noqa: ANN001, ANN202
    profile = tmp / "work-profile"
    (profile / "projects").mkdir(parents=True)
    accounts = {"provider_accounts": {"accounts": [{"id": "work", "name": "Work", "provider": "claude", "claude_config_dir": str(profile)}]}}
    install.env.config_path.write_text(json.dumps(accounts))
    env = replace(install.env, claude_homes=(*install.env.claude_homes, profile))
    return replace(install, env=env), profile


def test_a_pinned_session_gets_its_files_in_its_profiles_home(tmp_path: Path) -> None:
    crate = export_world(tmp_path)
    install, profile = _with_profile(target_install(tmp_path, crate), tmp_path)
    receipt = run(crate, install)
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    enc = slugify_project_dir(crate.world.root1)
    assert (profile / "projects" / enc / f"{CONV_A}.jsonl").is_file()
    assert not (install.claude / "projects" / enc / f"{CONV_A}.jsonl").exists()
    assert receipt.checks["resume_unverified"] == {}, "the receipt must measure the home recreate will use"


def test_a_todo_that_differs_here_does_not_keep_the_conversation_out(tmp_path: Path) -> None:
    crate = export_world(tmp_path)
    install = target_install(tmp_path, crate)
    todo = install.claude / "todos" / f"{CONV_A}-agent-{CONV_A}.json"
    todo.parent.mkdir(parents=True)
    todo.write_text('{"rewritten": "by claude after the export"}')
    with cf.open_crate(crate.path) as reader:
        plan = build_plan(reader, install.env, ImportRequest(), crate_sha256=crate.sha256, encrypted=False)
    assert plan["ok"], plan["blockers"]
    run(crate, install)
    assert todo.read_text() == '{"rewritten": "by claude after the export"}', "local wins"
    assert (install.claude / "projects" / slugify_project_dir(crate.world.root1) / f"{CONV_A}.jsonl").is_file()


def _record(role: str, rel: str, enc_folder: str, *, line_mode: bool = False) -> FileRecord:
    return FileRecord(role=role, home="claude", home_index=0, rel=rel, source_path=None, conversation_id=None, family="claude",
                      enc_folder=enc_folder, length=3, content_sha256="0" * 64, chain_sha256="0" * 64, chunks=(), line_mode=line_mode,
                      lines=None, ends_with_newline=False, mode=0o600, mtime_ns=None, origin="test", vault_signature=None, redactions=None)


def test_memory_stays_in_this_imports_folder_and_under_memory(tmp_path: Path) -> None:
    crate = export_world(tmp_path)
    env = target_install(tmp_path, crate).env
    enc = {"-mine": EncEntry("-mine", "-mine-new", "launch", "/mine")}
    ok = files_place.destination(_record("memory", "projects/-mine/memory/MEMORY.md", "-mine"), env, enc, own=True, include_instructions=True)
    assert ok[0] == files_place.ACT_PLACE and ok[1].parts[-3:] == ("-mine-new", "memory", "MEMORY.md")
    other = files_place.destination(_record("memory", "projects/-realproj/memory/MEMORY.md", "-mine"), env, enc, own=True, include_instructions=True)
    assert other[0] == files_place.ACT_KEPT, "a forged rel naming another project's folder is kept in the crate"
    outside = files_place.destination(_record("memory", "projects/-mine/notes.md", "-mine"), env, enc, own=True, include_instructions=True)
    assert outside[0] == files_place.ACT_KEPT, "a memory role file outside memory/ is kept"


def test_a_crate_cannot_make_a_non_transcript_file_growable_by_claiming_line_mode(tmp_path: Path) -> None:
    dest = tmp_path / "todo.json"
    dest.write_bytes(b"abc")
    record = _record("todo", "todos/x.json", "-mine", line_mode=True)
    record = replace(record, length=6)

    class Reader:
        def file_chunks(self, _record):  # noqa: ANN001, ANN201
            yield b"abcdef"

    cls, _why = files_place.classify(dest, record, Reader())  # type: ignore[arg-type]
    assert cls == files_place.CLASS_CONFLICT
