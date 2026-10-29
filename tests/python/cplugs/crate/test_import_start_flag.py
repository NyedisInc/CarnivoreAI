
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.cplugs.crate.routes_imports import add_to, has_start_route


def test_start_route_flag_follows_the_registered_routes() -> None:
    router = APIRouter(prefix="/cplugs/crate")
    router.add_api_route("/imports/plan", lambda: None, methods=["POST"])
    assert has_start_route(router) is False

    router.add_api_route("/imports", lambda: None, methods=["GET"])
    assert has_start_route(router) is False

    full = APIRouter(prefix="/cplugs/crate")
    add_to(full, Depends(lambda: None))
    assert has_start_route(full) is True
