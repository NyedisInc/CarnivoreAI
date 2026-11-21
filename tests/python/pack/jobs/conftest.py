
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from src.core.pack.reserve.holds import HOLDS


@pytest.fixture(autouse=True)
def _empty_holds() -> Iterator[None]:
    HOLDS._entries.clear()
    yield
    HOLDS._entries.clear()


@pytest.fixture(autouse=True)
def _own_home(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    if "_ssh_" not in request.module.__name__:
        return
    home = tmp_path_factory.mktemp("home-")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
