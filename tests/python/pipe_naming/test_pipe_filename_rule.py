
from __future__ import annotations

from pathlib import Path

import pytest

from src.core import pipe_liveness
from src.core.pipe_liveness import PaneReading, classify_ownership
from src.core.tmux_backend import TmuxBackend


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_log_dir", lambda self: tmp_path)


def _adopt(name: str) -> TmuxBackend:
    return TmuxBackend.for_external(session_name=name, working_dir=Path("/tmp"))


def _readopt(name: str) -> TmuxBackend:
    return TmuxBackend(
        session_id=f"adopted:{name}", working_dir=Path("/tmp"), session_name=name
    )


@pytest.mark.parametrize("name", ["cloude_demo", "cloude_cloudecode-2", "my proj", "cloude_ses_1a2b"])
def test_adopt_and_readopt_resolve_the_same_file(name):
    assert _adopt(name)._resolve_pipe_path() == _readopt(name)._resolve_pipe_path()


def test_created_backend_with_the_same_tmux_name_agrees_too():
    created = TmuxBackend(
        session_id="ses_1a2b", working_dir=Path("/tmp"), session_name="cloude_demo"
    )
    assert created._resolve_pipe_path() == _adopt("cloude_demo")._resolve_pipe_path()


def test_distinct_tmux_names_keep_distinct_files():
    assert _adopt("foo")._resolve_pipe_path() != _adopt("cloude_foo")._resolve_pipe_path()


def test_legacy_paths_cover_every_old_spelling_and_exclude_the_current_one():
    backend = _readopt("cloude_demo")
    current = str(backend._resolve_pipe_path())
    legacy = backend._legacy_pipe_paths()
    names = {Path(p).name for p in legacy}
    assert "tmux_ext_cloude_demo.pipe" in names
    assert "tmux_adopted_cloude_demo.pipe" in names
    assert current not in legacy


def _reading(owner: str) -> PaneReading:
    return PaneReading(dead=False, piped=True, activity_epoch=1, signature="0:0:0", owner=owner)


def test_own_copier_under_an_old_name_is_migrated_not_flagged_as_theft():
    backend = _readopt("cloude_demo")
    expected = str(backend._resolve_pipe_path())
    old = str(Path(expected).parent / "tmux_ext_cloude_demo.pipe")
    verdict = classify_ownership(_reading(old), expected, True, backend._legacy_pipe_paths())
    assert verdict == pipe_liveness.LEGACY_OWNER
    assert verdict in pipe_liveness.REISSUE_VERDICTS
    assert verdict not in pipe_liveness.THEFT_VERDICTS


def test_a_genuine_stranger_is_still_foreign():
    backend = _readopt("cloude_demo")
    expected = str(backend._resolve_pipe_path())
    verdict = classify_ownership(
        _reading("/somewhere/else/tmux_other.pipe"), expected, True, backend._legacy_pipe_paths()
    )
    assert verdict == pipe_liveness.FOREIGN_OWNER
    assert verdict in pipe_liveness.THEFT_VERDICTS


def test_matching_owner_is_still_owned():
    backend = _readopt("cloude_demo")
    expected = str(backend._resolve_pipe_path())
    assert classify_ownership(_reading(expected), expected, True, backend._legacy_pipe_paths()) == pipe_liveness.OWNED
