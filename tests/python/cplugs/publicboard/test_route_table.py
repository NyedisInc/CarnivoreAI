
from __future__ import annotations

import pytest

from src.cplugs.publicboard import routes
from src.cplugs.publicboard.edge import EdgeConfig, PublicEdge

FROZEN_ROUTES: frozenset = frozenset({("GET", "/"), ("GET", "/app.js"), ("GET", "/app.css"), ("GET", "/api/board")})
FROZEN_PATTERNS = [("GET", r"/f/([A-Za-z0-9_-]{22}\.r[1-9][0-9]{0,5}\.[a-z][a-z0-9-]{0,23}\.[0-9]{10}\.[A-Za-z0-9_-]{43})")]


def test_the_public_table_equals_the_frozen_set_exactly() -> None:
    assert frozenset(routes.ROUTES) == FROZEN_ROUTES


def test_the_pattern_routes_equal_the_frozen_list_exactly() -> None:
    assert [(method, regex.pattern) for method, regex, _ in routes.PATTERN_ROUTES] == FROZEN_PATTERNS


def test_no_route_can_write() -> None:
    assert {method for method, _ in routes.ROUTES} | {method for method, _, _ in routes.PATTERN_ROUTES} == {"GET"}


def test_the_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        routes.ROUTES[("GET", "/api/board")] = lambda *a: None  # type: ignore[index]


def test_the_edge_is_wired_to_the_real_table_by_default() -> None:
    assert PublicEdge(EdgeConfig.of(["203.0.113.11"], ["review.example.test"])).routes is routes.ROUTES
