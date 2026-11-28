
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import retention_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.config.retention import RetentionConfig  # noqa: E402
from src.core.retention import service as service_mod  # noqa: E402
from src.core.retention.paths import RetentionPaths, default_paths  # noqa: E402
from src.core.retention.service import RetentionService  # noqa: E402
from tests.python.retention.conftest import make_file  # noqa: E402


def _client(svc: RetentionService, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(service_mod, "_service", svc)
    app = FastAPI()
    app.include_router(retention_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def test_the_run_route_defaults_to_a_dry_run_and_a_real_run_acts(roots: RetentionPaths, service: RetentionService, monkeypatch: pytest.MonkeyPatch) -> None:
    for n in range(1, 5):
        make_file(roots.state_dir / f"carnivore.db.bak-v{n}-x.nobackup", 8, age_seconds=(9 - n) * 86_400)
    c = _client(service, monkeypatch)
    dry = c.post("/api/v1/maintenance/retention/run").json()
    assert dry["dry_run"] and dry["counts"] == {"planned": 2} and len(list(roots.state_dir.iterdir())) == 4
    assert c.get("/api/v1/maintenance/retention").json()["last_run"] is None
    real = c.post("/api/v1/maintenance/retention/run", json={"dry_run": False}).json()
    assert real["counts"] == {"done": 2} and len(list(roots.state_dir.iterdir())) == 2
    assert c.get("/api/v1/maintenance/retention").json()["last_run"]["counts"] == {"done": 2}


def test_the_routes_require_auth() -> None:
    app = FastAPI()
    app.include_router(retention_routes.router, prefix="/api/v1")
    assert TestClient(app).get("/api/v1/maintenance/retention").status_code in (401, 403)


def test_config_defaults_match_joes_decisions() -> None:
    cfg = RetentionConfig()
    assert (cfg.enabled, cfg.keep_db_backups, cfg.keep_rollback_bundles, cfg.menubar_log_cap_mb, cfg.interval_seconds) == (True, 2, 2, 50, 86_400)


def test_default_paths_come_from_the_given_home_and_env_not_the_real_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = default_paths(tmp_path / "state", home=tmp_path / "h")
    assert p.rollback_dir == tmp_path / "h/Library/Application Support/Carnivore-rollback"
    assert p.menubar_log_dir == tmp_path / "h/Library/Application Support/Carnivore Menubar/logs" and str(p.drive_root) == "/Volumes/Backup"
    monkeypatch.setenv("CARNIVORE_ROLLBACK_DIR", str(tmp_path / "rb"))
    assert default_paths(tmp_path / "state", home=tmp_path / "h").rollback_dir == tmp_path / "rb"
