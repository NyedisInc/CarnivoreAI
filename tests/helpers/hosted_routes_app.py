
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import (
    catalog_community_routes,
    catalog_community_write_routes,
    catalog_email_signin_routes,
    catalog_google_signin_routes,
    catalog_hosted_routes,
    catalog_rating_routes,
)
from src.api.auth import require_auth
from src.core.catalog import hosted_api
from src.core.catalog.services import CatalogServices
from src.core.catalog.trust_root import TrustRoot

TEST_API_BASE_URL = "https://catalog.test.invalid/api/v1"


class StateOnlyReader:

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


@dataclass
class HostedProxyApp:

    client: TestClient
    sent: List[httpx.Request] = field(default_factory=list)
    state: Path = Path(".")

    def paths(self) -> List[str]:
        return [request.url.path for request in self.sent]


@contextlib.contextmanager
def hosted_proxy_app(
    tmp_path: Path,
    *,
    responder: Callable[[httpx.Request], httpx.Response],
    api_base_url: str = TEST_API_BASE_URL,
    include_aggregator: bool = False,
) -> Iterator[HostedProxyApp]:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)

    record = HostedProxyApp(client=None, state=state)  # type: ignore[arg-type]

    def handle(request: httpx.Request) -> httpx.Response:
        record.sent.append(request)
        return responder(request)

    transport = httpx.MockTransport(handle)
    fake = httpx.AsyncClient(transport=transport, follow_redirects=False)

    async def shared_client() -> httpx.AsyncClient:
        return fake

    catalog = CatalogServices(
        trust_root=TrustRoot(index_key=None, publisher_key=None),
        index_cache=None,  # type: ignore[arg-type]
        staged_plans=None,  # type: ignore[arg-type]
        open_db=lambda: None,  # type: ignore[arg-type,return-value]
        index_url=lambda: "https://catalog.test.invalid/v1/index.json",
        api_base_url=lambda: api_base_url,
    )

    class Services:

        def __init__(self) -> None:
            self.catalog = catalog
            self.settings_reader = StateOnlyReader(state)

    previous = hosted_api.shared_client
    hosted_api.shared_client = shared_client  # type: ignore[assignment]
    try:
        app = FastAPI()
        if include_aggregator:
            from src.api import routes as api_routes

            app.include_router(api_routes.router)
        else:
            app.include_router(catalog_hosted_routes.router)
            app.include_router(catalog_rating_routes.router)
            app.include_router(catalog_email_signin_routes.router)
            app.include_router(catalog_google_signin_routes.router)
            app.include_router(catalog_community_routes.router)
            app.include_router(catalog_community_write_routes.router)
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        app.state.services = Services()
        with TestClient(app) as client:
            record.client = client
            yield record
    finally:
        hosted_api.shared_client = previous  # type: ignore[assignment]


def json_responder(
    answers: Dict[str, Any],
    *,
    status: int = 200,
) -> Callable[[httpx.Request], httpx.Response]:

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=answers)

    return respond


def route_responder(
    routes: Dict[str, Any],
    *,
    fallback: Optional[httpx.Response] = None,
) -> Callable[[httpx.Request], httpx.Response]:

    def respond(request: httpx.Request) -> httpx.Response:
        for suffix, answer in routes.items():
            if request.url.path.endswith(suffix):
                resolved = answer(request) if callable(answer) else answer
                status, body = resolved
                return httpx.Response(status, json=body)
        if fallback is not None:
            return fallback
        return httpx.Response(404, json={"code": "not_found", "detail": "no such route"})

    return respond
