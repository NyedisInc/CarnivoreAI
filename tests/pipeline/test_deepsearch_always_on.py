
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from src.cplugs.host import runtime
from src.core.deepsearch import pipeline_plugin

ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = re.compile(r"save_pipeline[./]search_index|save_pipeline import search_index")


def test_nothing_imports_the_old_search_index_path():
    scanned = [p for top in ("src", "scripts", "tests") for p in (ROOT / top).rglob("*.py") if "__pycache__" not in p.parts]
    assert len(scanned) > 500
    assert any("src/core/deepsearch/" in str(p) for p in scanned)
    offenders = [str(p.relative_to(ROOT)) for p in scanned
                 if p != Path(__file__).resolve() and OLD_PATH.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert offenders == []
    assert not (ROOT / "src/core/save_pipeline/search_index").exists()
    assert (ROOT / "src/core/deepsearch/grouped.py").is_file() and pipeline_plugin.DEEPSEARCH is not None


def test_deep_search_is_not_a_plugin_so_nothing_can_switch_it_off():
    assert runtime.find("deepsearch") is None
    assert "deepsearch" not in {d.id for d in runtime.definitions()}
    assert len(runtime.definitions()) > 5


def test_the_rebuild_route_answers(monkeypatch):
    from src.api import pipeline_plugin_routes as routes

    monkeypatch.setattr(routes.runtime, "rebuild_plugin", lambda pid: {"plugin": pid, "dropped_bytes": 0, "files_marked": 0})
    from fastapi import FastAPI
    from src.api.auth import require_auth  # noqa: PLC0415

    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    answer = TestClient(app).post("/api/v1/pipeline/plugins/deepsearch/rebuild")
    assert answer.status_code == 202 and answer.json()["plugin"] == "deepsearch"
