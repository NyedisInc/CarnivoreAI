
from __future__ import annotations

import hashlib
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest

from src.core.crate_import import apply as ap
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.db import connect, db_path_for, transaction
from src.core.project_writes import insert_project_row
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_format.golden_read import identity_for
from tests.python.crate_import.install import Install, make_install
from tests.python.crate_import.test_import_same_path import rows_of

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "crate"
GOLDEN = [("v1", "project-own.crate"), ("v1", "project-share.crate"), ("v1", "session-own.crate"), ("v1", "session-own.crate.age"),
          ("v1.1", "project-own.crate"), ("v1.1", "session-own.crate")]


def seed_target_project(install: Install) -> int:
    root = str(install.projects / "golden-home")
    Path(root).mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path_for(install.state))) as conn:
        with transaction(conn):
            row, _tomb, _adopted = insert_project_row(conn, root=root, raw_path=root, name="golden-home", uid=None, source="user")
    return int(row["id"])


def restore(path: Path, install: Install, request: ImportRequest) -> Tuple[Dict[str, Any], Optional[ap.ImportReceipt]]:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with cf.open_crate(path, identity_for(path)) as reader:
        plan = build_plan(reader, install.env, request, crate_sha256=sha, encrypted=path.name.endswith(".age"))
        if not plan["ok"]:
            return plan, None
        receipt = ap.apply_import(reader, install.env, request, crate_sha256=sha, fingerprint=plan["fingerprint"],
                                  import_id=new_import_id())
    return plan, receipt


@pytest.mark.parametrize("folder,name", GOLDEN)
def test_every_golden_crate_imports_into_an_empty_install(tmp_path: Path, folder: str, name: str) -> None:
    path = FIXTURES / folder / name
    install = make_install(tmp_path)
    request = ImportRequest(mode="relocate", new_root=str(install.projects / "golden-restored"))
    plan, receipt = restore(path, install, request)
    if receipt is None and any(b["code"] == "project_choice_needed" for b in plan["blockers"]):
        request = ImportRequest(target_project_id=seed_target_project(install))
        plan, receipt = restore(path, install, request)
    assert receipt is not None, plan["blockers"]
    assert plan["provenance"] == "foreign"
    assert receipt.state in ("done", "done_with_warnings"), receipt.warnings
    assert receipt.checks["file_mismatch"] == [] and receipt.checks["resume_unverified"] == {}

    sessions = rows_of(install, "SELECT lifecycle, lifecycle_source, tmux_name, origin, claude_session_uuid FROM sessions")
    assert sessions, "every golden crate carries at least one session"
    assert {(s["lifecycle"], s["tmux_name"], s["origin"]) for s in sessions} == {("stopped", None, "imported")}

    recorded = set()
    with cf.open_crate(path, identity_for(path)) as reader:
        recorded = {(f.home, f.content_sha256) for f in reader.files() if f.role in ("transcript", "subagent", "todo", "file_history")}
    placed = {hashlib.sha256(p.read_bytes()).hexdigest() for home in (install.claude, install.codex) for p in home.rglob("*") if p.is_file()}
    assert recorded and {sha for _home, sha in recorded} <= placed, "every conversation file of the crate is on disk, byte for byte"
