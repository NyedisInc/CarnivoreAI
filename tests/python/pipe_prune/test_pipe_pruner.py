
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.pipe_prune import prune_once
from src.core.pipe_prune.gather import parse_pane_rows
from src.core.pipe_prune.plan import PaneFacts

NOW = 1_800_000_000.0
DAY = 24 * 3600.0
OLD = NOW - 3 * DAY
FRESH = NOW - 60.0


def _pipe(d: Path, name: str, mtime: float) -> Path:
    p = d / name
    p.write_bytes(b"x" * 10)
    os.utime(p, (mtime, mtime))
    return p


def _facts(*names: str, owners: tuple = ()) -> PaneFacts:
    return PaneFacts(True, frozenset(names), frozenset(owners))


def _run(d: Path, facts: PaneFacts, *, opened=frozenset(), ladder=True) -> dict:
    return prune_once(
        d,
        socket_name="throwaway",
        ladder_done=ladder,
        min_age_seconds=DAY,
        now=NOW,
        read_panes_fn=lambda _s: facts,
        open_files_fn=lambda _p: opened,
    )


def test_gone_and_old_is_pruned_present_is_kept(tmp_path):
    gone = _pipe(tmp_path, "tmux_cloude_gone.pipe", OLD)
    here = _pipe(tmp_path, "tmux_cloude_here.pipe", OLD)
    out = _run(tmp_path, _facts("cloude_here"))
    assert not gone.exists() and here.exists()
    assert out["pruned"] == 1 and out["refused"] is None


def test_unknown_tmux_answer_never_prunes(tmp_path):
    f = _pipe(tmp_path, "tmux_cloude_gone.pipe", OLD)
    out = _run(tmp_path, PaneFacts(complete=False))
    assert f.exists() and out["pruned"] == 0 and out["refused"]


def test_zero_panes_refuses(tmp_path):
    f = _pipe(tmp_path, "tmux_cloude_gone.pipe", OLD)
    out = _run(tmp_path, _facts())
    assert f.exists() and out["refused"] == "zero_panes_read"


def test_legacy_named_file_of_a_present_session_is_kept(tmp_path):
    keep = [
        _pipe(tmp_path, "tmux_ext_cloude_a.pipe", OLD),
        _pipe(tmp_path, "tmux_adopted_cloude_a.pipe", OLD),
        _pipe(tmp_path, "tmux_ses_1a2b.pipe", OLD),
    ]
    _run(tmp_path, _facts("cloude_a", "cloude_ses_1a2b"))
    assert all(p.exists() for p in keep)


def test_legacy_named_file_of_a_gone_session_is_pruned(tmp_path):
    f = _pipe(tmp_path, "tmux_ext_cloude_dead.pipe", OLD)
    g = _pipe(tmp_path, "tmux_adopted_cloude_dead.pipe", OLD)
    _run(tmp_path, _facts("cloude_other"))
    assert not f.exists() and not g.exists()


def test_young_file_is_kept(tmp_path):
    f = _pipe(tmp_path, "tmux_cloude_new.pipe", FRESH)
    out = _run(tmp_path, _facts("cloude_other"))
    assert f.exists() and out["pruned"] == 0


def test_file_named_by_a_live_pane_is_kept_even_with_an_unrelated_name(tmp_path):
    f = _pipe(tmp_path, "tmux_weird.pipe", OLD)
    _run(tmp_path, _facts("cloude_other", owners=(str(f),)))
    assert f.exists()


def test_file_open_by_a_process_is_kept(tmp_path):
    f = _pipe(tmp_path, "tmux_cloude_gone.pipe", OLD)
    _run(tmp_path, _facts("cloude_other"), opened=frozenset({os.path.realpath(f)}))
    assert f.exists()


def test_open_check_unavailable_refuses(tmp_path):
    f = _pipe(tmp_path, "tmux_cloude_gone.pipe", OLD)
    out = prune_once(
        tmp_path, socket_name="t", ladder_done=True, min_age_seconds=DAY, now=NOW,
        read_panes_fn=lambda _s: _facts("cloude_other"), open_files_fn=lambda _p: None,
    )
    assert f.exists() and out["refused"] == "open_file_check_unavailable"


def test_ladder_not_consumed_deletes_nothing(tmp_path):
    f = _pipe(tmp_path, "tmux_cloude_gone.pipe", OLD)
    out = _run(tmp_path, _facts("cloude_other"), ladder=False)
    assert f.exists() and out["refused"] == "import_ladder_not_yet_consumed"


def test_non_pipe_rotated_mirror_and_symlink_are_untouched(tmp_path):
    keep = [
        _pipe(tmp_path, "tmux_cloude_gone.pipe.1", OLD),
        _pipe(tmp_path, "tmux_rh_box_x.pipe", OLD),
        _pipe(tmp_path, "notes.txt", OLD),
    ]
    target = _pipe(tmp_path, "real.dat", OLD)
    link = tmp_path / "tmux_cloude_link.pipe"
    link.symlink_to(target)
    _run(tmp_path, _facts("cloude_other"))
    assert all(p.exists() for p in keep) and link.is_symlink() and target.exists()


def test_pane_rows_incomplete_on_a_malformed_row():
    assert parse_pane_rows("cloude_a\t/p/a.pipe\ncloude_b\n").complete is False
    ok = parse_pane_rows("cloude_a\t/p/a.pipe\ncloude_b\t\n")
    assert ok.complete and ok.session_names == {"cloude_a", "cloude_b"}
    assert ok.owner_paths == {"/p/a.pipe"}


def test_ladder_consumed_never_creates_the_database_and_answers_false(tmp_path):
    from src.core.db import db_path_for
    from src.core.pipe_prune.runner import ladder_consumed

    assert ladder_consumed(tmp_path) is False
    assert not db_path_for(tmp_path).exists()


def test_run_survives_a_database_error_in_one_pass(tmp_path, monkeypatch):
    import asyncio
    import sqlite3

    from src.core.pipe_prune import runner

    monkeypatch.setattr(runner, "FIRST_PASS_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(runner, "INTERVAL_SECONDS", 0.0)
    pruner = runner.PipePruner(log_dir=tmp_path, state_dir=tmp_path, socket_name="throwaway")
    calls = []

    def boom(_age):
        calls.append(1)
        raise sqlite3.OperationalError("database is locked")

    pruner._pass = boom

    async def drive():
        task = asyncio.create_task(pruner.run())
        for _ in range(50):
            await asyncio.sleep(0.01)
            if len(calls) >= 2:
                break
        alive = not task.done()
        task.cancel()
        return alive

    assert asyncio.run(drive()) and len(calls) >= 2
