from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.session_records_routes import router


def test_the_remove_route_is_not_registered() -> None:
    paths = {(m, r.path) for r in router.routes for m in getattr(r, "methods", ())}
    assert ("POST", "/sessions/records/{session_uuid}/remove") not in paths
    assert ("DELETE", "/sessions/records/{session_uuid}") in paths
    assert ("POST", "/sessions/records/{session_uuid}/unarchive") in paths
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    assert TestClient(app).post("/api/v1/sessions/records/any-uuid/remove").status_code in (404, 405)
