
from __future__ import annotations

from typing import Iterator

import pytest

from src.core.attention import codex_lock_holders


@pytest.fixture(autouse=True)
def _no_lock_hints() -> Iterator[None]:
    codex_lock_holders._hints.clear()
    yield
    codex_lock_holders._hints.clear()


@pytest.fixture(autouse=True)
def _no_codex_read_memory() -> Iterator[None]:
    from src.core.attention import codex_read_cache

    codex_read_cache.clear()
    yield
    codex_read_cache.clear()
