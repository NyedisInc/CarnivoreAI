
from __future__ import annotations

import shutil
from typing import Iterator

import pytest

from tests.tui.offline_stub import Stub, make_stub


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stub]:
    made = make_stub(monkeypatch)
    try:
        yield made
    finally:
        shutil.rmtree(made.root, ignore_errors=True)
