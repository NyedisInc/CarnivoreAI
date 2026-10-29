
from __future__ import annotations

from contextlib import closing
from typing import Callable, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.api import projects_service
from src.api.auth import require_auth
from src.api.session_background_image_routes import _read_capped
from src.config import settings
from src.core import resource_push, terminal_background
from src.core.companies import hero_art_gen, hero_images, hero_thumbs, store
from src.core.resource_push import topics as resource_topics

logger = structlog.get_logger()
router = APIRouter(tags=["companies"])

_NOT_AN_IMAGE = "unsupported image type; png, jpeg, gif, webp and avif are accepted"


def _company_id(company_id: int) -> int:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        try:
            store.get_company(conn, company_id)
        except store.CompanyNotFound:
            raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
    return company_id


def _project_id(project_name: str) -> int:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        return projects_service.resolve_target(conn, project_name)["id"]


def _notify(kind: str) -> None:
    resource_push.notify(resource_topics.COMPANIES if kind == hero_images.COMPANY else resource_topics.PROJECTS)


async def _put(kind: str, row_id: int, file: UploadFile) -> dict:
    max_bytes = settings.load_auth_config().uploads.max_size_mb * 1024 * 1024
    data = await _read_capped(file, max_bytes)
    ext = terminal_background.sniff_image_extension(data[: terminal_background.SNIFF_LENGTH])
    logger.info("api_upload_hero_image", kind=kind, row_id=row_id, size=len(data), sniffed=ext)
    if ext is None:
        raise HTTPException(status_code=415, detail=_NOT_AN_IMAGE)
    try:
        _, rev = hero_images.store(kind, row_id, ext, data)
    except OSError as exc:
        logger.error("hero_image_write_failed", kind=kind, row_id=row_id, error=str(exc))
        raise HTTPException(status_code=500, detail="could not store the image") from exc
    _notify(kind)
    return {"has_image": True, "image_rev": rev}


_IMMUTABLE = "private, max-age=31536000, immutable"
_REVALIDATE = "no-cache, must-revalidate"


def _get(kind: str, row_id: int, rev: Optional[str], size: Optional[str]) -> FileResponse:
    path = hero_images.find(kind, row_id)
    media_type = terminal_background.content_type_for_extension(path.suffix.lstrip(".")) if path else None
    if path is None or media_type is None:
        raise HTTPException(status_code=404, detail="no stored image")
    current = hero_images.rev_of(path)
    cache = _IMMUTABLE if rev is not None and rev == current else _REVALIDATE
    if size is not None:
        thumb = hero_thumbs.thumb_for(kind, row_id, path, size)
        if thumb is not None:
            return FileResponse(thumb, media_type="image/webp", headers={"Cache-Control": cache})
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": cache})


def _delete(kind: str, row_id: int) -> dict:
    hero_images.remove_upload(kind, row_id)
    _notify(kind)
    return hero_images.fields(kind, row_id)


def _regenerate(kind: str, row_id: int, name: str, root: Optional[str]) -> dict:
    if hero_images.find_upload(kind, row_id) is not None:
        raise HTTPException(status_code=409, detail="remove the uploaded image first; an upload always wins")
    hero_art_gen.schedule(kind, row_id, name, root, regenerate=True)
    return {"queued": True}


def _bind(kind: str, resolve: Callable, names: Callable) -> None:
    path = "/companies/{key}/image" if kind == hero_images.COMPANY else "/projects/{key}/image"
    auth = [Depends(require_auth)]

    async def put_image(key: str, file: UploadFile) -> dict:
        return await _put(kind, resolve(key), file)

    def get_image(key: str, rev: Optional[str] = None, size: Optional[Literal["thumb", "card", "banner"]] = None) -> FileResponse:
        return _get(kind, resolve(key), rev, size)

    def delete_image(key: str) -> dict:
        return _delete(kind, resolve(key))

    def regenerate_image(key: str) -> dict:
        row_id = resolve(key)
        name, root = names(key, row_id)
        return _regenerate(kind, row_id, name, root)

    router.add_api_route(
        path + "/regenerate", regenerate_image, methods=["POST"], status_code=202, dependencies=auth,
        name=f"{kind}_regenerate_image",
    )
    for method, handler in (("PUT", put_image), ("GET", get_image), ("DELETE", delete_image)):
        router.add_api_route(path, handler, methods=[method], dependencies=auth, name=f"{kind}_{handler.__name__}")


def _company_key(key: str) -> int:
    if not key.isdigit():
        raise HTTPException(status_code=404, detail=f"Company '{key}' not found")
    return _company_id(int(key))


def _company_names(_key: str, company_id: int) -> tuple:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        return store.get_company(conn, company_id)["name"], None


def _project_names(key: str, _project_id: int) -> tuple:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        row = projects_service.resolve_target(conn, key)
    return row.get("display_name") or key, row.get("root")


_bind(hero_images.COMPANY, _company_key, _company_names)
_bind(hero_images.PROJECT, _project_id, _project_names)
