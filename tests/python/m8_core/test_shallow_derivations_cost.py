from __future__ import annotations

from contextlib import closing
from pathlib import Path

from src.core import session_project_binding as spb
from src.core.db_models import SESSION_ATTRIBUTION_DERIVED_DEEPEST
from tests.test_session_project_binding import _add_project, _add_session, _conn, state_dir  # noqa: F401


def test_canonical_runs_a_bounded_number_of_times(state_dir: Path, tmp_path: Path, monkeypatch) -> None:  # noqa: F811
    home = tmp_path / "home"
    projects = []
    with closing(_conn(state_dir)) as conn:
        with conn:
            top = _add_project(conn, str(home), "home")
            for i in range(6):
                folder = home / f"p{i}"
                folder.mkdir(parents=True)
                projects.append(_add_project(conn, str(folder), f"p{i}"))
            for i in range(30):
                _add_session(conn, name=f"s{i}", epoch=i + 1, working_dir=str(home / f"p{i % 6}"),
                             project_id=top, attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST)
        calls = []
        real = spb.canonical
        monkeypatch.setattr(spb, "canonical", lambda p: calls.append(p) or real(p))
        with conn:
            assert spb.correct_shallow_derivations(conn) == 30
    assert len(calls) <= 7 + 6 + 1
