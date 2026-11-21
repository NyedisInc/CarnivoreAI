
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.plugins.reviewboard.public import routes
from src.plugins.reviewboard.public.edge import EdgeConfig, PublicEdge

FROZEN_ROUTES: frozenset = frozenset({("GET", "/"), ("GET", "/publicboard.js"), ("GET", "/publicboard.css"), ("GET", "/api/board"),
                                      ("POST", "/api/comments"), ("POST", "/api/draft"), ("GET", "/api/next")})
FROZEN_WRITES = {("POST", "/api/comments"), ("POST", "/api/draft")}
FROZEN_PATTERNS = [("GET", r"/f/([A-Za-z0-9_-]{22}\.r[1-9][0-9]{0,5}\.[a-z][a-z0-9-]{0,23}\.[0-9]{10}\.[A-Za-z0-9_-]{43})")]


def test_the_public_table_equals_the_frozen_set_exactly() -> None:
    assert frozenset(routes.ROUTES) == FROZEN_ROUTES


def test_the_pattern_routes_equal_the_frozen_list_exactly() -> None:
    assert [(method, regex.pattern) for method, regex, _ in routes.PATTERN_ROUTES] == FROZEN_PATTERNS


def test_only_the_comment_and_the_autosave_write() -> None:
    assert {key for key in routes.ROUTES if key[0] != "GET"} == FROZEN_WRITES
    assert {method for method, _, _ in routes.PATTERN_ROUTES} == {"GET"}


def test_the_docs_checklist_equals_the_table_both_ways() -> None:
    text = (Path(__file__).resolve().parents[5] / "docs" / "reviewboard-public-links.md").read_text(encoding="utf-8")
    start = text.index("**What the owner's reverse proxy must forward**")
    paragraph = text[start:text.index("\n\n", start)]
    listed = set(re.findall(r"`(GET|POST) (/[^`\s]*)`", paragraph))
    assert listed == set(routes.ROUTES) | {("GET", "/f/<ticket>")}


def test_the_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        routes.ROUTES[("GET", "/api/board")] = lambda *a: None  # type: ignore[index]


def test_the_edge_is_wired_to_the_real_table_by_default() -> None:
    assert PublicEdge(EdgeConfig.of(["203.0.113.11"], ["review.example.test"])).routes is routes.ROUTES
