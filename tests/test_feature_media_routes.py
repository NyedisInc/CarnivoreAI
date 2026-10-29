
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.feature_media_routes import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _signed_in_client() -> TestClient:
    client = _client()
    client.app.dependency_overrides[require_auth] = lambda: {}
    return client


def test_unauthenticated_refused() -> None:
    response = _client().get("/api/v1/feature-media/sidebar-help-panel/panel.png")
    assert response.status_code == 401


def test_missing_feature_directory_is_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.feature_media_routes.repo_root", lambda: tmp_path)
    response = _signed_in_client().get("/api/v1/feature-media/no-such-feature/panel.png")
    assert response.status_code == 404


def test_missing_file_is_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.feature_media_routes.repo_root", lambda: tmp_path)
    (tmp_path / "features" / "media" / "sidebar-help-panel").mkdir(parents=True)
    response = _signed_in_client().get("/api/v1/feature-media/sidebar-help-panel/panel.png")
    assert response.status_code == 404


def test_real_file_served_with_correct_content_type(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.feature_media_routes.repo_root", lambda: tmp_path)
    folder = tmp_path / "features" / "media" / "sidebar-help-panel"
    folder.mkdir(parents=True)
    (folder / "panel.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    response = _signed_in_client().get("/api/v1/feature-media/sidebar-help-panel/panel.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"\x89PNG\r\n\x1a\n" + b"0" * 16


def test_gif_and_svg_content_types(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.feature_media_routes.repo_root", lambda: tmp_path)
    folder = tmp_path / "features" / "media" / "sidebar-help-panel"
    folder.mkdir(parents=True)
    (folder / "a.gif").write_bytes(b"GIF89a")
    (folder / "b.svg").write_bytes(b"<svg></svg>")
    client = _signed_in_client()
    assert client.get("/api/v1/feature-media/sidebar-help-panel/a.gif").headers["content-type"] == "image/gif"
    assert client.get("/api/v1/feature-media/sidebar-help-panel/b.svg").headers["content-type"] == "image/svg+xml"


def test_dotdot_traversal_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.feature_media_routes.repo_root", lambda: tmp_path)
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"top secret")
    (tmp_path / "features" / "media" / "sidebar-help-panel").mkdir(parents=True)
    response = _signed_in_client().get(
        "/api/v1/feature-media/sidebar-help-panel/..%2f..%2fsecret.png"
    )
    assert response.status_code in (404, 400)
    assert response.status_code != 200


def test_slash_in_filename_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.feature_media_routes.repo_root", lambda: tmp_path)
    (tmp_path / "features" / "media" / "sidebar-help-panel").mkdir(parents=True)
    response = _signed_in_client().get(
        "/api/v1/feature-media/sidebar-help-panel/sub%2ffile.png"
    )
    assert response.status_code == 404


def test_feature_id_with_uppercase_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.feature_media_routes.repo_root", lambda: tmp_path)
    folder = tmp_path / "features" / "media" / "Sidebar-Help-Panel"
    folder.mkdir(parents=True)
    (folder / "panel.png").write_bytes(b"data")
    response = _signed_in_client().get("/api/v1/feature-media/Sidebar-Help-Panel/panel.png")
    assert response.status_code == 404


def test_symlink_escaping_folder_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.feature_media_routes.repo_root", lambda: tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not yours")
    folder = tmp_path / "features" / "media" / "sidebar-help-panel"
    folder.mkdir(parents=True)
    (folder / "panel.png").symlink_to(outside)
    response = _signed_in_client().get("/api/v1/feature-media/sidebar-help-panel/panel.png")
    assert response.status_code == 404


def test_unsupported_extension_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.api.feature_media_routes.repo_root", lambda: tmp_path)
    folder = tmp_path / "features" / "media" / "sidebar-help-panel"
    folder.mkdir(parents=True)
    (folder / "script.sh").write_bytes(b"#!/bin/sh\necho hi")
    response = _signed_in_client().get("/api/v1/feature-media/sidebar-help-panel/script.sh")
    assert response.status_code == 404
