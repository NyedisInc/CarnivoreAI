
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from src.core.session_token_usage import reader_state
from tests.python.reader_state import fixture_subagents, fixture_tree, subagent_reads, timer_mail_reads

REPO = Path(__file__).resolve().parents[3]
READERS = [reader_state._resolve(m, a).persist.name for m, a in reader_state.PERSISTED_CACHES]


def _run(phase: str, root: Path, state: Path) -> Dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-m", "tests.python.reader_state.restart_driver", phase, str(root), str(state)],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads((root / f"out-{phase}.json").read_text())


def _check_subagent_reader(name: str, restart: Dict[str, Any], cold: Dict[str, Any]) -> None:
    assert restart["nonempty"] > 0
    changed = fixture_subagents.changed_agent_stems()
    if name in (subagent_reads.LEDGER, subagent_reads.NOTICES):
        assert set(changed) <= set(cold["cold_parses"])
        assert len(set(cold["cold_parses"])) >= fixture_subagents.N_AGENTS
        assert restart["cold_parses"] == changed
    else:
        assert cold["cold_parses"] and not restart["cold_parses"]


def _check_mirror(first: Dict[str, Any], restart: Dict[str, Any], cold: Dict[str, Any]) -> None:
    rewritten, unchanged = set(fixture_tree.REWRITTEN), set(fixture_tree.UNCHANGED)
    assert set(cold["cold_reads"]) == set(fixture_tree.all_names())
    assert set(restart["cold_reads"]) == rewritten
    assert restart["backlog"] == cold["backlog"]
    assert all(cold["backlog"][name] for name in fixture_tree.all_names() if name not in rewritten)
    for name in fixture_tree.all_names():
        if name in rewritten:
            continue
        assert not set(restart["delivered"][name]) & set(first["delivered"][name])
        assert f"claude:{name}-native-u3" in restart["delivered"][name]
        seen = {tuple(item) for item in first["events"][name] + restart["events"][name]}
        assert seen == {tuple(item) for item in cold["events"][name]}
    assert all(restart["delivered"][name] == [f"claude:{name}-native-u3"] for name in unchanged)
    assert restart["events"]["s0"] and restart["events"]["s0"] != cold["events"]["s0"]


def _check_timer_mail_reader(name: str, first: Dict[str, Any], restart: Dict[str, Any],
                             cold: Dict[str, Any]) -> None:
    unchanged = set(fixture_tree.UNCHANGED)
    assert restart["nonempty"] > 0
    if name == timer_mail_reads.MIRROR:
        _check_mirror(first, restart, cold)
        return
    assert restart["md5"] == cold["md5"]
    assert unchanged <= set(cold["cold_parses"])
    assert not unchanged & set(restart["cold_parses"])
    assert set(restart["cold_parses"]) == set(fixture_tree.REWRITTEN)


@pytest.mark.parametrize("case", [*READERS, "corrupt_store"])
def test_restart_resume_equals_cold_read(tmp_path: Path, case: str) -> None:
    root, state = tmp_path / "tree", tmp_path / "state"
    root.mkdir()
    first = _run("phase1", root, state)
    assert first["rows"].get(case if case != "corrupt_store" else READERS[0], 0) > 0
    fixture_tree.apply_phase2(root)
    if case == "corrupt_store":
        (state / "reader_state.db").write_bytes(b"this is not a sqlite database" * 50)
        for suffix in ("-wal", "-shm"):
            (state / f"reader_state.db{suffix}").unlink(missing_ok=True)
    restart = _run("restart", root, state)
    cold = _run("cold", root, state)
    assert restart["md5"] == cold["md5"]
    for name in subagent_reads.NAMES + (timer_mail_reads.TIMERS,):
        assert restart["readers"][name]["md5"] == cold["readers"][name]["md5"], name
    if case in subagent_reads.NAMES:
        _check_subagent_reader(case, restart["readers"][case], cold["readers"][case])
        return
    if case in timer_mail_reads.NAMES:
        assert restart["hydrated"][case] > 0
        _check_timer_mail_reader(case, first["readers"][case], restart["readers"][case], cold["readers"][case])
        return
    unchanged = set(fixture_tree.UNCHANGED)
    assert unchanged <= set(cold["cold_parses"])
    if case == "corrupt_store":
        assert "reader_state_store_reset" in restart["events"]
        assert restart["loaded"] == 0
        return
    assert restart["loaded"] > 0
    assert not unchanged & set(restart["cold_parses"])
    assert set(restart["cold_parses"]) == set(fixture_tree.REWRITTEN)
