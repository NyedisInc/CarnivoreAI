
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_acg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_acg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.config.catalog import CATALOG_KEY, CatalogConfig  # noqa: E402
from src.core import app_config_guard, config_files  # noqa: E402
from src.core.app_config_guard import APP_CONFIG_PROTECTED  # noqa: E402
from src.core.catalog.client import DEFAULT_INDEX_URL  # noqa: E402
from src.core.catalog.hosted_api import DEFAULT_API_BASE_URL  # noqa: E402


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "a-project"
    root.mkdir()
    (root / "config.json").write_text('{"mine": true}')
    return root


@pytest.fixture
def app_config(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "server" / "config.json"
    path.parent.mkdir()
    path.write_text('{"jwt_secret": "x"}')
    monkeypatch.setattr(
        app_config_guard, "app_config_path", lambda: path, raising=True
    )
    return path




def test_the_app_config_is_recognised_through_a_relative_spelling(app_config):
    indirect = app_config.parent / "." / "config.json"

    assert app_config_guard.is_app_config(indirect) is True


def test_the_app_config_is_recognised_through_a_symlinked_directory(
    app_config, tmp_path
):
    link = tmp_path / "linked-server"
    link.symlink_to(app_config.parent, target_is_directory=True)

    assert app_config_guard.is_app_config(link / "config.json") is True


def test_the_app_config_is_recognised_through_a_dot_dot_spelling(app_config):
    indirect = app_config.parent / "sub" / ".." / "config.json"
    (app_config.parent / "sub").mkdir()

    assert app_config_guard.is_app_config(indirect) is True


def test_the_app_config_is_recognised_through_a_case_folded_spelling(app_config):
    assert app_config_guard.is_app_config(app_config.parent / "Config.json") is True


def test_the_app_config_is_recognised_through_an_upper_case_spelling(app_config):
    assert app_config_guard.is_app_config(app_config.parent / "CONFIG.JSON") is True


def test_a_projects_own_config_json_is_not_the_app_config(app_config, project):
    assert app_config_guard.is_app_config(project / "config.json") is False


def test_a_projects_own_case_folded_config_json_is_not_the_app_config(
    app_config, project
):
    assert app_config_guard.is_app_config(project / "Config.json") is False


def test_the_guard_answers_for_a_config_that_does_not_exist_yet(
    tmp_path, monkeypatch
):
    absent = tmp_path / "not-created" / "config.json"
    monkeypatch.setattr(
        app_config_guard, "app_config_path", lambda: absent, raising=True
    )

    assert app_config_guard.is_app_config(absent) is True




def test_writing_the_app_config_is_refused_and_the_bytes_are_untouched(
    app_config, monkeypatch
):
    before = app_config.read_bytes()
    monkeypatch.setattr(
        config_files,
        "resolve_safe_path",
        lambda root_id, rel_path, project_path: app_config,
        raising=True,
    )

    with pytest.raises(app_config_guard.AppConfigProtectedError):
        config_files.write_file(
            root_id="workdir",
            rel_path="config.json",
            content='{"jwt_secret": "stolen"}',
            project_path=str(app_config.parent),
        )

    assert app_config.read_bytes() == before
    assert not (app_config.parent / "config.json.bak").exists()


def test_a_projects_own_config_json_is_still_writable(app_config, project):
    result = config_files.write_file(
        root_id="workdir",
        rel_path="config.json",
        content='{"mine": false}',
        project_path=str(project),
    )

    assert result["backed_up"] is True
    assert json.loads((project / "config.json").read_text()) == {"mine": False}


def test_the_refusal_is_not_a_config_file_error(app_config, monkeypatch):
    monkeypatch.setattr(
        config_files,
        "resolve_safe_path",
        lambda root_id, rel_path, project_path: app_config,
        raising=True,
    )

    with pytest.raises(app_config_guard.AppConfigProtectedError) as caught:
        config_files.write_file(
            root_id="workdir",
            rel_path="config.json",
            content="{}",
            project_path=str(app_config.parent),
        )

    assert not isinstance(caught.value, config_files.ConfigFileError)


def test_the_code_the_route_answers_with_is_stable():
    assert APP_CONFIG_PROTECTED == "app_config_protected"




def test_the_index_url_default_is_the_carnivore_url():
    assert CatalogConfig().index_url == DEFAULT_INDEX_URL
    assert DEFAULT_INDEX_URL == "https://catalog.carnivore.ai/v1/index.json"


def test_the_index_url_is_overridable():
    override = "https://example.invalid/catalog/index.json"

    assert CatalogConfig(index_url=override).index_url == override


def test_the_api_base_url_default_is_the_catalog_host():
    assert CatalogConfig().api_base_url == DEFAULT_API_BASE_URL
    assert DEFAULT_API_BASE_URL == "https://api.carnivore.ai/v1"


def test_the_catalog_block_hangs_off_the_config_json_key():
    from src.config.auth import AuthConfig  # noqa: PLC0415

    assert CATALOG_KEY == "catalog"
    assert CATALOG_KEY in AuthConfig.model_fields


def test_a_config_predating_the_catalog_block_still_loads():
    from src.config.auth import AuthConfig  # noqa: PLC0415

    loaded = AuthConfig(totp_secret="t", jwt_secret="j")

    assert loaded.catalog.index_url == DEFAULT_INDEX_URL


def test_the_index_url_is_read_through_the_settings_port(monkeypatch):
    from src.config import settings as live_settings  # noqa: PLC0415
    from src.config.auth import AuthConfig  # noqa: PLC0415

    override = "https://example.invalid/v1/index.json"
    monkeypatch.setattr(
        type(live_settings),
        "load_auth_config",
        lambda self: AuthConfig(
            totp_secret="t",
            jwt_secret="j",
            catalog=CatalogConfig(index_url=override),
        ),
        raising=True,
    )

    assert live_settings.get_catalog_index_url() == override




@pytest.fixture
def http(tmp_path):
    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from src.api import config_files_routes  # noqa: PLC0415
    from src.api.auth import require_auth  # noqa: PLC0415

    app = FastAPI()
    app.include_router(config_files_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def test_the_route_answers_409_with_the_code(http, app_config):
    response = http.post(
        "/api/v1/config-files/write",
        json={
            "root": "workdir",
            "path": "config.json",
            "content": "{}",
            "project_path": str(app_config.parent),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == APP_CONFIG_PROTECTED
    assert app_config.read_text() == '{"jwt_secret": "x"}'


@pytest.mark.parametrize("spelling", ["Config.json", "CONFIG.JSON"])
def test_the_route_refuses_a_case_folded_spelling_of_the_app_config(
    http, app_config, spelling
):
    response = http.post(
        "/api/v1/config-files/write",
        json={
            "root": "workdir",
            "path": spelling,
            "content": '{"jwt_secret": "stolen"}',
            "project_path": str(app_config.parent),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == APP_CONFIG_PROTECTED
    assert app_config.read_text() == '{"jwt_secret": "x"}'
    assert not (app_config.parent / "config.json.bak").exists()


def test_the_route_still_writes_a_projects_own_case_folded_config_json(
    http, app_config, project
):
    response = http.post(
        "/api/v1/config-files/write",
        json={
            "root": "workdir",
            "path": "Config.json",
            "content": '{"mine": false}',
            "project_path": str(project),
        },
    )

    assert response.status_code == 200
    assert json.loads((project / "Config.json").read_text()) == {"mine": False}


def test_the_route_still_writes_a_projects_own_config_json(http, app_config, project):
    response = http.post(
        "/api/v1/config-files/write",
        json={
            "root": "workdir",
            "path": "config.json",
            "content": '{"mine": false}',
            "project_path": str(project),
        },
    )

    assert response.status_code == 200
    assert json.loads((project / "config.json").read_text()) == {"mine": False}
