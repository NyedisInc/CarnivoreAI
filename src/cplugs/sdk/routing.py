
from __future__ import annotations

from typing import Any, Callable, Dict, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.routing import APIRoute

from fastapi import HTTPException

from src.api.auth import limiter, require_auth, security
from src.security_headers import OWN_POLICY_HEADER


_PUBLIC_ROUTES: Dict[Tuple[str, str], str] = {}


def public_routes() -> Dict[Tuple[str, str], str]:
    return dict(_PUBLIC_ROUTES)


def router_prefix(cplug_id: str, third_party: bool = False) -> str:
    return f"/cplugs/{cplug_id}/r" if third_party else f"/cplugs/{cplug_id}"


def cplug_router(cplug_id: str, third_party: bool = False) -> APIRouter:
    from src.cplugs.host.runtime import require_enabled  # noqa: PLC0415

    return APIRouter(prefix=router_prefix(cplug_id, third_party), tags=[f"cplug:{cplug_id}"],
                     dependencies=[Depends(require_auth), Depends(require_enabled(cplug_id))])


def cplug_context(cplug_id: str) -> Callable[[Request], Any]:
    def dependency(request: Request) -> Any:
        from src.cplugs.host.runtime import host_for  # noqa: PLC0415

        return host_for(request.app).context(cplug_id, request=request)

    return dependency


def add_public_get(router: APIRouter, cplug_id: str, path: str, endpoint: Callable[..., Any], reason: str = "") -> None:
    from src.cplugs.host.runtime import require_enabled  # noqa: PLC0415

    router.routes.append(APIRoute(f"{router.prefix}{path}", endpoint, methods=["GET"], dependencies=[Depends(require_enabled(cplug_id))],
                                  tags=list(router.tags)))
    _record(router, "GET", path, reason)


def add_public_post(router: APIRouter, cplug_id: str, path: str, endpoint: Callable[..., Any], reason: str = "") -> None:
    from src.cplugs.host.runtime import require_enabled  # noqa: PLC0415

    router.routes.append(APIRoute(f"{router.prefix}{path}", endpoint, methods=["POST"], dependencies=[Depends(require_enabled(cplug_id))],
                                  tags=list(router.tags)))
    _record(router, "POST", path, reason)


def _record(router: APIRouter, method: str, path: str, reason: str) -> None:
    if reason:
        _PUBLIC_ROUTES[(method, f"{router.prefix}{path}")] = reason


async def has_valid_bearer(request: Request) -> bool:
    credentials = await security(request)
    if not credentials:
        return False
    try:
        await require_auth(credentials, request)
    except HTTPException:
        return False
    return True


def rate_limited(spec: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return limiter.limit(spec)
