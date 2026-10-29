
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.attention.registry_read import (
    REG_ABSENT,
    REG_OK,
    REG_UNREADABLE,
    pane_id_of,
    parse_registry_record,
    read_registry_index,
)
from src.core.claude_resume_argv import list_process_table
from src.core.listing_attention import attention_reads_for_name
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import TEST_SOCKET_NAME

CONVERSATION = "e8a50968-3979-425d-8c15-fe26076e389f"


def _index_of(*records):
    return {record.tmux_name: record for record in records}


def _record(target: str, pid: int, session_id: str = CONVERSATION):
    return parse_registry_record(
        {"pid": pid, "status": "idle", "sessionId": session_id, "tmux": target},
        path_pid=pid,
    )


def _reads(name, index, *, pane_id, pane_pid, parents):
    registry, _transcript = attention_reads_for_name(
        name,
        registry_index=index,
        session_started_epoch=None,
        claude_session_uuid=None,
        working_dir=None,
        pane_id=pane_id,
        pane_pid=pane_pid,
        process_parents=parents,
        transcript_reader=lambda *_a, **_k: None,
    )
    return registry




@pytest.mark.parametrize(
    "target, expected",
    [
        ("cloude_Orchard-4:@100.%100", "%100"),
        ("a:@1.%7", "%7"),
        ("no-colon-here", None),
        ("cloude_a:@1", None),
        ("cloude_a:@1.%x", None),
        ("cloude_a:@1.7", None),
        (None, None),
    ],
)
def test_pane_id_of_reads_only_a_real_pane_id(target, expected):
    assert pane_id_of(target) == expected


def test_a_renamed_session_matches_its_record_by_pane_and_pid_ancestry():
    record = _record("cloude_Orchard-4:@100.%100", pid=4883)
    parents = {4883: 4851, 4851: 1}
    registry = _reads(
        "cloude_Orchard-Rename", _index_of(record),
        pane_id="%100", pane_pid=4851, parents=lambda: parents,
    )
    assert registry.verdict == REG_OK
    assert registry.session_uuid == CONVERSATION
    assert registry.pid == 4883


def test_a_record_for_a_different_pane_never_matches():
    record = _record("cloude_other:@101.%101", pid=4883)
    parents = {4883: 4851, 4851: 1}
    registry = _reads(
        "cloude_Orchard-Rename", _index_of(record),
        pane_id="%100", pane_pid=4851, parents=lambda: parents,
    )
    assert registry.verdict == REG_ABSENT


def test_the_same_pane_id_on_another_tmux_server_never_matches():
    record = _record("mytmux:@100.%100", pid=5000)
    parents = {5000: 4999, 4999: 1, 4851: 1}
    registry = _reads(
        "cloude_Orchard-Rename", _index_of(record),
        pane_id="%100", pane_pid=4851, parents=lambda: parents,
    )
    assert registry.verdict == REG_ABSENT


def test_an_unreadable_process_table_is_not_a_match():
    record = _record("cloude_Orchard-4:@100.%100", pid=4883)
    registry = _reads(
        "cloude_Orchard-Rename", _index_of(record),
        pane_id="%100", pane_pid=4851, parents=lambda: None,
    )
    assert registry.verdict == REG_ABSENT


def test_two_proven_records_on_one_pane_are_a_refusal():
    first = _record("cloude_a:@100.%100", pid=4883)
    second = _record("cloude_b:@100.%100", pid=4585, session_id="x")
    parents = {4883: 4851, 4585: 4851, 4851: 1}
    registry = _reads(
        "cloude_Orchard-Rename", _index_of(first, second),
        pane_id="%100", pane_pid=4851, parents=lambda: parents,
    )
    assert registry.verdict == REG_UNREADABLE


def test_a_name_hit_never_reads_the_process_table():
    record = _record("cloude_a:@1.%1", pid=4883)

    def boom():
        raise AssertionError("process table read on a name hit")

    registry = _reads(
        "cloude_a", _index_of(record), pane_id="%1", pane_pid=4851, parents=boom,
    )
    assert registry.verdict == REG_OK



requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True, text=True, check=False,
    )


def _write_record(directory: str, pid: int, target: str) -> None:
    now_ms = int(time.time() * 1000)
    with open(os.path.join(directory, "%d.json" % pid), "w") as handle:
        json.dump({
            "pid": pid, "status": "idle", "sessionId": CONVERSATION,
            "tmux": target, "startedAt": now_ms, "statusUpdatedAt": now_ms,
        }, handle)


@requires_tmux
def test_real_tmux_rename_keeps_the_record_matched_and_a_foreign_pane_does_not():
    old = "cloude_rr_%s" % uuid.uuid4().hex[:6]
    new = old + "_renamed"
    created = _tmux("new-session", "-d", "-s", old, "-x", "80", "-y", "24", "sleep 300")
    assert created.returncode == 0, created.stderr
    registry_dir = tempfile.mkdtemp(prefix="cc_regrename_")
    try:
        ids = _tmux("list-panes", "-t", old, "-F", "#{window_id}.#{pane_id}|#{pane_pid}")
        target_tail, pane_pid_raw = ids.stdout.strip().split("|")
        pane_pid = int(pane_pid_raw)
        _write_record(registry_dir, pane_pid, "%s:%s" % (old, target_tail))

        assert _tmux("rename-session", "-t", old, new).returncode == 0

        backend = TmuxBackend(
            session_id="rr-probe", working_dir=Path.home(), on_output=None,
            socket_name=TEST_SOCKET_NAME,
        )
        listing = backend.list_pane_status_all()
        row = {r["name"]: r for r in listing.sessions}[new]
        assert row["pane_id"] == target_tail.split(".")[-1]
        assert row["pid"] == pane_pid

        def parents():
            return {p.pid: p.ppid for p in (list_process_table() or [])}

        index = read_registry_index(registry_dir)
        registry = _reads(
            new, index, pane_id=row["pane_id"], pane_pid=row["pid"], parents=parents,
        )
        assert registry.verdict == REG_OK
        assert registry.session_uuid == CONVERSATION

        os.remove(os.path.join(registry_dir, "%d.json" % pane_pid))
        _write_record(registry_dir, pane_pid, "%s:@99999.%%99999" % old)
        registry = _reads(
            new, read_registry_index(registry_dir),
            pane_id=row["pane_id"], pane_pid=row["pid"], parents=parents,
        )
        assert registry.verdict == REG_ABSENT
    finally:
        _tmux("kill-session", "-t", new)
        _tmux("kill-session", "-t", old)
        shutil.rmtree(registry_dir, ignore_errors=True)
