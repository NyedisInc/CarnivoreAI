
from __future__ import annotations

from typing import Iterator

import pytest

from src.core.tmux_control.reader import close_readers


@pytest.fixture(autouse=True)
def _close_control_readers() -> Iterator[None]:
    yield
    close_readers()
