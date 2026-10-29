
from __future__ import annotations

import pytest

from src.cplugs.publicboard import routes
from src.cplugs.publicboard.edge import EdgeConfig, PublicEdge

FROZEN_ROUTES: frozenset = frozenset()


def test_the_public_table_equals_the_frozen_set_exactly() -> None:
    assert frozenset(routes.ROUTES) == FROZEN_ROUTES


def test_the_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        routes.ROUTES[("GET", "/api/board")] = lambda *a: None  # type: ignore[index]


def test_the_edge_is_wired_to_the_real_table_by_default() -> None:
    assert PublicEdge(EdgeConfig.of(["203.0.113.11"], ["review.example.test"])).routes is routes.ROUTES
