
from __future__ import annotations

from typing import List, Tuple

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.api.catalog_contents_routes import view_of_version
from src.core.catalog.theme_palettes import derive_palettes
from src.core.catalog.verify_items import latest_version
from src.models.catalog import CatalogItem, ItemVersion
from src.models.catalog_theme_palettes import ThemePalettesResponse

router = APIRouter(tags=["catalog"])


@router.get(
    "/catalog/theme-palettes",
    response_model=ThemePalettesResponse,
    dependencies=[Depends(require_auth)],
)
async def catalog_theme_palettes(request: Request) -> ThemePalettesResponse:
    """The reduced palette of every trusted theme in the held index.

    Output: ThemePalettesResponse - an empty answer when no index is held.
    Example: GET /api/v1/catalog/theme-palettes -> {"items": {...}, "pending": []}
    """
    services = request.app.state.services
    snapshot = await services.catalog.index_cache.get()
    if snapshot.verified is None:
        return ThemePalettesResponse()
    themes: List[Tuple[CatalogItem, ItemVersion]] = []
    for item in snapshot.verified.items:
        version = latest_version(item) if item.kind == "theme" else None
        if version is not None:
            themes.append((item, version))

    async def read(item: CatalogItem, version: ItemVersion):
        return await view_of_version(services, item, version)

    cache_dir = services.settings_reader.state_dir() / "catalog_theme_palettes"
    items, pending = await derive_palettes(themes, read, cache_dir, snapshot.verified.serial)
    return ThemePalettesResponse(items=items, pending=pending)
