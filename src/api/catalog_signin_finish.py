
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

from src.api.error_response import api_error
from src.core.catalog import client_sessions as cs
from src.core.catalog.token_store import CatalogSession
from src.core.relay_identity import device_key as dk

SWITCH_ROUTE = "/api/v1/catalog/computer-account/use"


def key_provider_for(request: Request) -> cs.KeyProvider:
    override = getattr(request.app.state, "catalog_device_key", None)
    if override is not None:
        return override
    from src.api.catalog_hosted_routes import install_id  # noqa: PLC0415

    async def provide() -> dk.DeviceKey:
        return await asyncio.to_thread(dk.load_or_create, install_id(request))

    return provide


def bound_account(request: Request) -> Optional[str]:
    import sqlite3  # noqa: PLC0415
    from contextlib import closing  # noqa: PLC0415

    from src.core.db import get_meta  # noqa: PLC0415
    from src.core.relay_identity.session import META_BOUND  # noqa: PLC0415

    try:
        with closing(request.app.state.services.catalog.open_db()) as conn:
            return get_meta(conn, META_BOUND) or None
    except sqlite3.Error:
        return None


async def finish_signin(
    request: Request, tokens: Dict[str, Any], provider: str, email: Optional[str] = None
) -> CatalogSession:
    services = request.app.state.services
    try:
        return await cs.complete_signin(
            services.settings_reader.state_dir(), services.catalog.api_base_url(), cs.client_ref(request),
            tokens, provider, email, key_provider_for(request),
        )
    except cs.ComputerSignedInAs as exc:
        login, handle = exc.login, exc.handle
        raise HTTPException(409, detail={
            "code": "computer_signed_in_as", "login": login, "switch": handle, "use": SWITCH_ROUTE,
            "detail": "this computer is signed in as a different account",
        }) from None
    except cs.ComputerNeedsSignIn:
        raise HTTPException(409, detail={
            "code": "computer_needs_sign_in",
            "detail": "this computer is signed out of carnivore; sign in on the computer itself",
        }) from None
    except cs.RefreshAndRetry:
        raise HTTPException(409, detail={
            "code": "refresh_and_retry", "detail": "refresh your session and try again",
        }) from None
    except ValueError as exc:
        raise api_error(502, "unavailable", exc) from None
