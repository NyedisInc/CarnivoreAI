
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, List, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import (
    catalog_contents_routes,
    catalog_install_routes,
    catalog_installed_routes,
    catalog_required_routes,
    catalog_routes,
    themes_routes,
)
from src.api.auth import require_auth
from src.core.catalog import archive_client
from src.core.catalog import client as catalog_client
from src.core.catalog.index_refresher import IndexRefresher
from src.core.catalog.services import build_catalog_services
from src.core.composition import build_services
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.ui_preferences_store import UiPreferencesStore
from tests.helpers.catalog_surface import INDEX_PATH, FrozenClock
from tests.helpers.static_http import StaticServer, self_signed_cert, serve_directory
from tests.test_skill_installer import FakeInstallRoots


class StateOnlySettings:

    def __init__(self, state: Path) -> None:
        self._state = state

    def pinned_themes_path(self) -> Path:
        return self._state / "pinned_themes.json"

    def log_buffer_size(self) -> int:
        return 1

    def state_dir(self) -> Path:
        return self._state

    def session_metadata_path(self) -> Path:
        return self._state / "session_metadata.json"


def register_projects(state: Path, roots: Iterable[Path]) -> None:
    with contextlib.closing(connect(db_path_for(state))) as conn:
        for index, root in enumerate(roots):
            conn.execute(
                "INSERT INTO projects (root, raw_path, display_name, source, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(root),
                    str(root),
                    f"project-{index}",
                    "test",
                    "2026-09-01T00:00:00Z",
                    "2026-09-01T00:00:00Z",
                ),
            )
        conn.commit()


@dataclass
class CatalogApp:

    client: TestClient
    server: StaticServer
    roots: FakeInstallRoots
    clock: FrozenClock
    services: Any
    index_url: str
    state: Path
    prefs: UiPreferencesStore

    def index_fetches(self) -> int:
        wanted = "/" + self.index_url.split("/", 3)[3]
        return sum(1 for path in self.server.seen() if path == wanted)

    def staging_entries(self) -> List[str]:
        staging = self.roots.staging_dir()
        if not staging.is_dir():
            return []
        return sorted(entry.name for entry in staging.iterdir())


class _SheetClient(TestClient):

    def raw_post(self, url, **kwargs):
        return super().post(url, **kwargs)

    def post(self, url, **kwargs):
        body = kwargs.get("json")
        if (
            url == "/catalog/install"
            and isinstance(body, dict)
            and not body.get("one_click")
            and body.get("consent") is None
            and not body.get("plan_token")
        ):
            preview = super().post("/catalog/install/preview", json=body)
            answer = preview.json() if preview.status_code in (200, 409) else {}
            if isinstance(answer.get("detail"), dict):
                answer = answer["detail"]
            token = answer.get("plan_token") if isinstance(answer, dict) else None
            if token:
                kwargs["json"] = {**body, "plan_token": token}
        return super().post(url, **kwargs)


@contextlib.contextmanager
def catalog_app(
    tmp_path: Path,
    served: Path,
    *,
    trust_root: Any,
    clock: Optional[FrozenClock] = None,
    index_path: str = INDEX_PATH,
    projects: Iterable[Path] = (),
    roots_factory: Optional[Callable[[Any], Any]] = None,
) -> Iterator[CatalogApp]:
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    cert = self_signed_cert(tls_dir)
    if cert is None:
        raise RuntimeError("no certificate could be made for the test server")

    ticking = clock or FrozenClock()
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    ensure_db_migrated(state, 4, "0.8.2")

    def open_db():
        return connect(db_path_for(state))

    if roots_factory is None:
        roots = FakeInstallRoots(tmp_path / "roots")
        roots.make_roots()
    else:
        roots = roots_factory(StateOnlySettings(state))

    config_path = tmp_path / "config.json"
    if not config_path.exists():
        config_path.write_text("{}\n", encoding="utf-8")
    prefs = UiPreferencesStore(lambda: config_path)
    if projects:
        register_projects(state, projects)

    with serve_directory(served, tls_cert=cert) as server:
        index_url = f"{server.base_url}/{index_path}"
        previous_base = archive_client.CODELOAD_BASE_URL
        archive_client.CODELOAD_BASE_URL = server.base_url
        try:
            catalog = build_catalog_services(
                index_url=lambda: index_url,
                api_base_url=lambda: "https://catalog.invalid/api/v1",
                clock=ticking,
                open_db=open_db,
                trust_root=trust_root,
            )
            services = build_services(
                clock=ticking,
                install_roots=roots,
                catalog=catalog,
                settings_reader=StateOnlySettings(state),
                ui_preferences=prefs,
            )
            app = FastAPI(lifespan=_client_lifespan(cert))
            app.include_router(catalog_contents_routes.router)
            app.include_router(catalog_required_routes.router)
            app.include_router(catalog_routes.router)
            app.include_router(catalog_install_routes.router)
            app.include_router(catalog_installed_routes.router)
            app.include_router(themes_routes.router)
            app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
            app.state.services = services
            app.state.ui_preferences_store = prefs
            app.state.catalog_index_refresher = IndexRefresher(catalog.index_cache)
            with _SheetClient(app) as client:
                yield CatalogApp(
                    client=client,
                    server=server,
                    roots=roots,
                    clock=ticking,
                    services=services,
                    index_url=index_url,
                    state=state,
                    prefs=prefs,
                )
        finally:
            archive_client.CODELOAD_BASE_URL = previous_base


def _client_lifespan(cert):

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        await catalog_client.init(verify=str(cert[0]))
        try:
            yield
        finally:
            await catalog_client.shutdown()

    return lifespan


def ledger_rows(app: CatalogApp) -> List[Any]:
    with app.services.catalog.ledger() as ledger:
        return list(ledger.list())
