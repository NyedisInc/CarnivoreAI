
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.settings import (
    NEW_DEFAULT_WORKING_DIR,
    Settings,
    migrate_default_working_dir,
)

OLD_TILDE = "~/cloude-projects"
OLD_EXPANDED = str(Path(OLD_TILDE).expanduser())


@pytest.mark.parametrize("old", [OLD_TILDE, OLD_EXPANDED, OLD_TILDE + "/"])
def test_old_default_maps_to_new(old: str) -> None:
    assert Settings(default_working_dir=old).default_working_dir == "~/carnivore-projects"


def test_custom_value_passes_through() -> None:
    assert Settings(default_working_dir="/srv/work").default_working_dir == "/srv/work"
    assert migrate_default_working_dir("~/my-projects") == "~/my-projects"


def test_unset_gets_new_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEFAULT_WORKING_DIR", raising=False)
    assert Settings(_env_file=None).default_working_dir == NEW_DEFAULT_WORKING_DIR
