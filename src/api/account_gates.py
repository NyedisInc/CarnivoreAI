"""The carnivore account gates: refuse NEW hosted-service actions while signed out (#1200, slice L4).

ONE LIST, TWO READERS. The gate ids live in
``src/api/account_gates.json`` (under src/ so every install ships it); the web bundle
imports it through Vite and this module reads it beside itself, so the UI and the server name the
same ids. Only ids marked ``server_enforced`` get a dependency here; the others
are listed for the UI.

GRACE: a gate only ever stops a NEW action (mint, enable, open a window). It
never reaches into anything already running; revoke, disable and status stay open.
The refusal body is TOP LEVEL, ``{"code": "account_required", "feature", "detail"}``,
the shape ``client/js/api.js`` keeps on ``err.body``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Awaitable, Callable, Dict, FrozenSet

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

from src.core.catalog import catalog_auth

logger = structlog.get_logger()

GATES_PATH = Path(__file__).resolve().with_name("account_gates.json")

ACCOUNT_REQUIRED = "account_required"


def _load() -> Dict[str, dict]:
    return json.loads(GATES_PATH.read_text(encoding="utf-8"))


GATES: Dict[str, dict] = _load()
SERVER_ENFORCED: FrozenSet[str] = frozenset(k for k, v in GATES.items() if v.get("server_enforced"))


class AccountRequired(Exception):

    def __init__(self, feature: str) -> None:
        super().__init__(feature)
        self.feature = feature


def account_required_handler(_request: Request, exc: AccountRequired) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"code": ACCOUNT_REQUIRED, "feature": exc.feature,
                 "detail": "sign in with a carnivore account to use this"},
    )


async def is_signed_in(request: Request) -> bool:
    services = request.app.state.services
    held = await catalog_auth.current(services.settings_reader.state_dir(), services.catalog.api_base_url())
    return held is not None


async def check(request: Request, feature: str) -> None:
    if not await is_signed_in(request):
        logger.info("account_gate_refused", feature=feature)
        raise AccountRequired(feature)


_dependencies: Dict[str, Callable[[Request], Awaitable[None]]] = {}


def require_account(feature: str) -> Callable[[Request], Awaitable[None]]:
    if feature not in SERVER_ENFORCED:
        raise ValueError(f"{feature} is not a server enforced account gate")
    if feature not in _dependencies:
        async def dependency(request: Request) -> None:
            await check(request, feature)
        _dependencies[feature] = dependency
    return _dependencies[feature]
