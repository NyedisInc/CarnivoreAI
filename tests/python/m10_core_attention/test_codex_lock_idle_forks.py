
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List

import pytest

from src.core.attention import codex_gather, codex_stores
from tests.python.m10_core_attention.codex_lock_fixtures import (
    CWD, THREAD, holding, lock_path, make_codex_home, release,
)

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS only")

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return make_codex_home(tmp_path)


@pytest.fixture
def holder(home: Path) -> Iterator[subprocess.Popen]:
    yield from holding(lock_path(home))


def _cycle(home: Path, pane_pid: int, monkeypatch: pytest.MonkeyPatch) -> dict:
    real_run = subprocess.run
    real_live = codex_gather.writer_lock_live
    lsof_calls: List[List[str]] = []
    live_answers: List[bool] = []

    def counting_run(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "lsof":
            lsof_calls.append(list(argv))
        return real_run(argv, *args, **kwargs)

    def spying_live(*args: Any, **kwargs: Any) -> bool:
        answer = real_live(*args, **kwargs)
        live_answers.append(answer)
        return answer

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", counting_run)
        patch.setattr(codex_gather, "writer_lock_live", spying_live)
        uuid = codex_stores.resolve_primary_uuid(
            str(home), pane_current_path=CWD, pane_title="", pane_pid=pane_pid, process_parents={},
        )
        if uuid:
            codex_gather.gather_codex_evidence(uuid, codex_home=str(home), now=NOW)
    return {"lsof": len(lsof_calls), "uuid": uuid, "lock_live": live_answers}


def test_unchanged_second_cycle_forks_no_lsof(home: Path, holder: subprocess.Popen,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    first = _cycle(home, holder.pid, monkeypatch)
    second = _cycle(home, holder.pid, monkeypatch)
    assert first["uuid"] == second["uuid"] == THREAD
    assert first["lock_live"] == second["lock_live"] == [True]
    assert second["lsof"] == 0, "an unchanged cycle forked lsof %d times" % second["lsof"]
    assert first["lsof"] == 0


def test_a_released_lock_reads_unheld_again(home: Path, holder: subprocess.Popen,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    assert _cycle(home, holder.pid, monkeypatch)["uuid"] == THREAD
    gone = holder.pid
    release(holder)
    assert _cycle(home, gone, monkeypatch)["uuid"] is None
    assert codex_stores.writer_lock_live(str(home), THREAD) is False
