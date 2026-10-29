
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.whats_new_routes import MAX_ENTRIES, router


def _client(tmp_path, monkeypatch, changes) -> TestClient:
    (tmp_path / "features").mkdir()
    index = {
        "areas": [],
        "catalog": [{"id": "f1", "name": "Feature one", "where": ["settings > one"], "how_to": ["tick it"]}],
        "changes": changes,
    }
    (tmp_path / "features" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr("src.api.features_routes.repo_root", lambda: tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {}
    return TestClient(app)


def _chg(n, kind="added", features=("f1",), day=None):
    return {"date": "2026-09-30", "type": kind, "features": list(features), "summary": f"s{n}",
            "landed_at": f"2026-09-30T10:{n:02d}:00Z"}


def test_unauthenticated_refused() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    assert TestClient(app).get("/api/v1/whats-new").status_code == 401


def test_only_later_user_visible_entries_with_where(tmp_path, monkeypatch) -> None:
    c = _client(tmp_path, monkeypatch, [_chg(1), _chg(2, "internal"), _chg(3, "fixed", ("nope",)), _chg(4)])
    body = c.get("/api/v1/whats-new", params={"since": "2026-09-30T10:01:00Z"}).json()
    assert body["mark"] == "2026-09-30T10:04:00Z"
    assert [e["summary"] for e in body["entries"]] == ["s4", "s3"]
    assert body["entries"][0]["where"] == ["settings > one"]
    assert body["entries"][0]["how_to"] == ["tick it"]
    assert body["entries"][1]["where"] == []


def test_no_since_returns_mark_only(tmp_path, monkeypatch) -> None:
    body = _client(tmp_path, monkeypatch, [_chg(1)]).get("/api/v1/whats-new").json()
    assert body["mark"] == "2026-09-30T10:01:00Z" and body["entries"] == []


def test_unknown_since_is_bounded_and_empty(tmp_path, monkeypatch) -> None:
    c = _client(tmp_path, monkeypatch, [_chg(1)])
    for bad in ("../../etc/passwd", "garbage", "x" * 150):
        body = c.get("/api/v1/whats-new", params={"since": bad}).json()
        assert body["entries"] == [] and body["total"] == 0


def test_cap_counts_the_rest(tmp_path, monkeypatch) -> None:
    c = _client(tmp_path, monkeypatch, [_chg(n % 60) | {"summary": f"s{n}", "landed_at": f"2026-09-30T{n // 60:02d}:{n % 60:02d}:00Z"} for n in range(1, 41)])
    body = c.get("/api/v1/whats-new", params={"since": "2026-09-29"}).json()
    assert len(body["entries"]) == MAX_ENTRIES and body["total"] == 40 and body["more"] == 10


def test_missing_index_is_clean(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.features_routes.repo_root", lambda: tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {}
    assert TestClient(app).get("/api/v1/whats-new").json()["available"] is False
