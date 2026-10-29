
from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[3]
TIMELINE_API = REPO / "web/src/opscenter/cells/timeline/api.ts"
PREFIX = re.compile(r"export const SAVE_PLUGIN_ROUTE = '([^']+)'")
_HOLE = re.compile(r"\$\{[^}]*\}")


def _restore_urls() -> List[str]:
    source = TIMELINE_API.read_text()
    prefix = PREFIX.search(source)
    assert prefix, "no SAVE_PLUGIN_ROUTE in the timeline api; the restore URL cannot be resolved"
    return [_HOLE.sub("x1", literal.replace("${SAVE_PLUGIN_ROUTE}", prefix.group(1)))
            for literal in re.findall(r"`([^`]*\$\{[^`]*/points/[^`]*/restore)`", source)]


@pytest.fixture
def anonymous() -> TestClient:
    from src.cplugs.host.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_the_widget_builds_a_restore_url():
    assert _restore_urls(), "no restore path found in the timeline api; the test would look at nothing"


def test_a_path_no_route_answers_is_a_404(anonymous):
    assert anonymous.post("/api/v1/time-machine/conversations/x1/points/x1/restore", json={}).status_code == 404


def test_open_a_copy_posts_to_a_route_the_save_plugin_mounts(anonymous):
    for url in _restore_urls():
        status = anonymous.post(f"/api/v1{url}", json={}).status_code
        assert status == 401, f"the timeline posts to {url}, which answered {status}, not a mounted route's 401"
