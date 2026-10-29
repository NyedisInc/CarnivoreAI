
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from src.core import static_asset_keys, theme_paths
from src.core.catalog import theme_migration
from src.core.static_serving import keyed_page_response, maybe_gzip_file_response, render_compressible_html_response, warm_static_gzip_cache
from src.core.version import resolve_version

logger = structlog.get_logger()


client_dir = Path(__file__).parent.parent.parent.parent / "client"


class NoCacheStaticFiles(StaticFiles):

    _NO_CACHE_SUFFIXES = (".js", ".html", ".json", ".css")

    def _cache_control_for(self, path: str, scope: dict) -> str:
        query = scope.get("query_string", b"")
        if b"v=" not in query:
            return static_asset_keys.REVALIDATE
        requested = parse_qs(query.decode("latin-1")).get("v", [""])[0]
        candidate = static_asset_keys.url_to_path(
            static_asset_keys.STATIC_PREFIX + path, Path(self.directory)
        )
        return static_asset_keys.cache_control_for(candidate, requested)

    async def get_response(self, path: str, scope: Scope) -> Response:
        keyed = keyed_page_response(path, scope, Path(self.directory))
        if keyed is not None:
            return keyed
        response = await super().get_response(path, scope)
        if path.lower().endswith(self._NO_CACHE_SUFFIXES):
            response.headers["Cache-Control"] = self._cache_control_for(path, scope)
            response = await maybe_gzip_file_response(response, scope)
        return response


_VERSION_PLACEHOLDER = "{{VERSION}}"
_CLIENT_BUILD_PLACEHOLDER = "{{CLIENT_BUILD}}"

APP_VERSION = resolve_version()


def _render_index_html() -> str:
    html = (client_dir / "index.html").read_text(encoding="utf-8")
    chip = f"v{APP_VERSION}" if APP_VERSION else ""
    html = html.replace(_VERSION_PLACEHOLDER, chip).replace(
        _CLIENT_BUILD_PLACEHOLDER, static_asset_keys.client_build_key(client_dir)
    )
    return static_asset_keys.render(html, client_dir)


_INDEX_HTML_GZIP_CACHE_KEY = "index.html:rendered"


def _render_index_html_response(request: Request) -> Response:
    return render_compressible_html_response(
        request, _render_index_html, client_dir / "index.html",
        _INDEX_HTML_GZIP_CACHE_KEY,
        fingerprint=static_asset_keys.shell_fingerprint,
    )


def _mount_user_themes(app: FastAPI) -> None:
    user_themes_dir = theme_paths.user_themes_dir()
    theme_migration.ensure_user_themes_dir()
    if user_themes_dir.exists():
        app.mount(
            "/themes",
            NoCacheStaticFiles(directory=str(user_themes_dir), html=False),
            name="user-themes",
        )
        logger.info("user_themes_mount", path=str(user_themes_dir))
    else:
        logger.info("user_themes_mount_skipped", path=str(user_themes_dir), reason="dir not present")


def install_static(app: FastAPI) -> None:
    app.mount("/static", NoCacheStaticFiles(directory=str(client_dir)), name="static")

    _warmed_count = warm_static_gzip_cache(client_dir, NoCacheStaticFiles._NO_CACHE_SUFFIXES)
    logger.info("static_gzip_cache_warmed", files=_warmed_count)

    _keyed_assets = static_asset_keys.warm(client_dir, client_dir / "index.html")
    logger.info("static_asset_keys_warmed", assets=_keyed_assets)
    _mount_user_themes(app)
