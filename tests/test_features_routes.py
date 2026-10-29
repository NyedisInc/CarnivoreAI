
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.features_routes import router
from src.api.auth import require_auth


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_unauthenticated_refused() -> None:
    assert _client().get("/api/v1/feature-catalog").status_code == 401


def test_missing_file_is_a_clean_empty_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.features_routes.repo_root", lambda: tmp_path)
    client = _client()
    client.app.dependency_overrides[require_auth] = lambda: {}
    response = client.get("/api/v1/feature-catalog")
    assert response.status_code == 200
    assert response.json() == {"available": False, "areas": [], "catalog": [], "changes": []}


def test_authenticated_reads_the_generated_index(tmp_path, monkeypatch) -> None:
    features_dir = tmp_path / "features"
    features_dir.mkdir()
    payload = {
        "areas": [{"id": "sidebar", "name": "Sidebar", "blurb": "the drawer"}],
        "catalog": [{"id": "help-panel", "name": "Help panel", "summary": "explains marks",
                      "area": "sidebar", "status": "stable", "since": "2026-09-24",
                      "updated": "2026-09-26"}],
        "changes": [
            {"date": "2026-09-26", "type": "added", "features": ["help-panel"],
             "summary": "add the releases view", "pr": 845, "release": "Unreleased"},
            {"date": "2026-09-20", "type": "internal", "features": [], "summary": "refactor",
             "pr": 1, "release": "v1.7.0"},
        ],
    }
    (features_dir / "index.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("src.api.features_routes.repo_root", lambda: tmp_path)
    client = _client()
    client.app.dependency_overrides[require_auth] = lambda: {}
    response = client.get("/api/v1/feature-catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["catalog"][0]["id"] == "help-panel"
    changes_by_summary = {c["summary"]: c for c in body["changes"]}
    assert changes_by_summary["add the releases view"]["release"] == "Unreleased"
    assert changes_by_summary["refactor"]["release"] == "v1.7.0"


def test_malformed_json_is_a_clean_empty_state(tmp_path, monkeypatch) -> None:
    features_dir = tmp_path / "features"
    features_dir.mkdir()
    (features_dir / "index.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("src.api.features_routes.repo_root", lambda: tmp_path)
    client = _client()
    client.app.dependency_overrides[require_auth] = lambda: {}
    response = client.get("/api/v1/feature-catalog")
    assert response.status_code == 200
    assert response.json()["available"] is False
