
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.plugins.reviewboard import root, wire
from src.plugins.reviewboard.errors import NoRoot


def test_the_filled_default_still_resolves_as_the_default(tmp_path: Path) -> None:
    path, is_default = root.resolve_root(str(tmp_path / "review-boards"), tmp_path)
    assert is_default and path == tmp_path / "review-boards"


def test_the_filled_default_is_not_offered_as_the_task_manager_folder(tmp_path: Path) -> None:
    ctx = SimpleNamespace(settings_now=lambda: {"boardsRoot": str(tmp_path / "review-boards")}, storage=SimpleNamespace(path=tmp_path / "cplugs" / "reviewboard"))
    with pytest.raises(NoRoot) as raised:
        wire.explicit_root(ctx)
    assert raised.value.reason == "unset"
