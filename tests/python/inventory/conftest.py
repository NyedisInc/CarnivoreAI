
from __future__ import annotations

from contextlib import closing
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from src.core.db import connect, db_path_for
from tests.python.inventory.world_build import build_world


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: Any) -> SimpleNamespace:
    return build_world(tmp_path_factory.mktemp("inventory-world"))


@pytest.fixture
def conn(seeded: SimpleNamespace) -> Iterator[Any]:
    with closing(connect(db_path_for(seeded.state))) as c:
        yield c
