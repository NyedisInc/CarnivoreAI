
from __future__ import annotations

import hashlib
import os
import secrets
import shlex
import time
from pathlib import Path
from typing import Dict, Iterator

import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_import import apply as ap
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.project_move.plan import PaneListing
from src.core.project_writes import insert_project_row
from src.core.work.storage import storage_for
from src.cplugs.sdk import crate_format as cf
from tests.python.crate_format.golden_read import FIXTURES_ROOT
from tests.python.crate_format.test_resume_drill_real import (
    EXIT_MARK, EXIT_WAIT_S, KEEP_ENV, LAST_PROMPT, NOT_FOUND_MARKERS, POLL_S, STARTUP_MARKERS, WAIT_S, _pane, _profile, _tmux,
    _to_trash, _trusted_parent, _wait_for, claude_bin,  # noqa: F401
)
from tests.python.inventory.world import CONV_A
from tests.socket_guard import derive_test_socket

FIXTURE = FIXTURES_ROOT / "v1.1" / "session-own.crate"


@pytest.fixture
def imported_place(tmp_path: Path, claude_bin: str) -> Iterator[Dict[str, Path]]:  # noqa: F811
    parent = _trusted_parent()
    if parent is None:
        pytest.skip("no_trusted_parent")
    folder = parent / f"crate-import-drill-{os.getpid()}-{secrets.token_hex(3)}"
    enc = _profile() / "projects" / slugify_project_dir(str(folder))
    assert not folder.exists() and not enc.exists()
    state, codex = tmp_path / "state", tmp_path / "codex"
    for made in (state, codex):
        made.mkdir()
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    storage_for(state).connect(True).close()
    env = ImportEnv(state=state, projects_dir=str(parent), claude_homes=(_profile(),), codex_home=codex, install_id="22222222-2222-4222-8222-222222222222",
                    panes=lambda: PaneListing(True), writers=lambda: (), free_bytes=lambda path: 10**12)
    folder.mkdir()
    try:
        with connect(db_path_for(state)) as conn, transaction(conn):
            project, _tombstone, _adopted = insert_project_row(conn, root=str(folder), raw_path=str(folder), name=folder.name, uid=None, source="user")
        request = ImportRequest(target_project_id=int(project["id"]))
        sha = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        with cf.open_crate(FIXTURE) as reader:
            plan = build_plan(reader, env, request, crate_sha256=sha, encrypted=False)
            assert plan["ok"], plan["blockers"]
            receipt = ap.apply_import(reader, env, request, crate_sha256=sha, fingerprint=plan["fingerprint"], import_id=new_import_id())
        assert receipt.state in ("done", "done_with_warnings") and (enc / f"{CONV_A}.jsonl").is_file(), receipt.warnings
        yield {"folder": folder, "enc": enc}
    finally:
        _to_trash(enc)
        _to_trash(folder)


def test_claude_resumes_the_imported_conversation(claude_bin: str, imported_place: Dict[str, Path]) -> None:  # noqa: F811
    socket = derive_test_socket("crate_import_drill")
    env = {k: os.environ[k] for k in KEEP_ENV if os.environ.get(k)}
    env["TERM"] = "xterm-256color"
    command = f"{shlex.quote(claude_bin)} --resume {CONV_A} --fork-session; echo {EXIT_MARK} $?; sleep 30"
    started = _tmux(socket, "new-session", "-d", "-s", "drill", "-x", "200", "-y", "50", "-c", str(imported_place["folder"]), command, env=env)
    assert started.returncode == 0, started.stderr
    try:
        seen = _wait_for(socket, (*STARTUP_MARKERS, *NOT_FOUND_MARKERS, LAST_PROMPT, EXIT_MARK), WAIT_S)
        if seen in STARTUP_MARKERS:
            pytest.skip(f"the pane shows a startup screen ({seen!r}); the drill never answers it")
        assert seen == LAST_PROMPT, f"resume did not show the last prompt (saw {seen!r}):\n{_pane(socket)[-2000:]}"
        _tmux(socket, "send-keys", "-t", "drill", "-l", "/exit")
        time.sleep(POLL_S)
        _tmux(socket, "send-keys", "-t", "drill", "Enter")
        assert _wait_for(socket, (EXIT_MARK,), EXIT_WAIT_S) == EXIT_MARK, _pane(socket)[-2000:]
    finally:
        _tmux(socket, "kill-server")
