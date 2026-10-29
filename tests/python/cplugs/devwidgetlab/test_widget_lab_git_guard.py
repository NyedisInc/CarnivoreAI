
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.devwidgetlab.drafts import ship
from tests.python.cplugs.devwidgetlab.draft_helpers import fake_repo, new_draft


def test_the_dry_run_names_the_missing_git_as_a_problem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.core.dev_tools.git_guard.git_available", lambda: False)
    made = new_draft(tmp_path / "s")
    plan = ship.plan(tmp_path / "s" / "drafts" / made["slug"], fake_repo(tmp_path / "repo"))
    assert ship.NO_GIT in plan["problems"]


