
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, Response

from src.core import static_asset_keys, static_cache

DEV_SKIP_PREFIXES: tuple[str, ...] = (
    "widget-harness-build/",
    "dist/widget-lab/",
    "style-guide/",
    "dist/style-guide-chunk-",
    "dist/widget-preview-chunk-",
)
DEV_SKIP_FILES: frozenset[str] = frozenset({
    "dist/style-guide.js",
    "dist/widget-preview.js",
    "dist/widget-preview.css",
})

CRITICAL_SHELL_FILES: tuple[str, ...] = (
    "index.html",
    "dist/app.js",
    "dist/app.css",
    "js/api.js",
)


def _is_dev_bundle(rel_posix: str) -> bool:
    if rel_posix in DEV_SKIP_FILES:
        return True
    return any(rel_posix.startswith(prefix) for prefix in DEV_SKIP_PREFIXES)


async def maybe_gzip_file_response(response: Response, scope: dict) -> Response:
    if not isinstance(response, FileResponse) or response.status_code != 200:
        return response
    request_headers = Headers(scope=scope)
    if "range" in request_headers:
        return response
    response.headers["Vary"] = "Accept-Encoding"
    accept_encoding = request_headers.get("accept-encoding", "")
    if "gzip" not in accept_encoding:
        return response
    stat_result = response.stat_result
    if stat_result is None:
        return response
    full_path = str(response.path)
    compressed = static_cache.peek(full_path, stat_result.st_mtime, stat_result.st_size)
    if compressed is None:
        path_obj = Path(full_path)
        compressed = await asyncio.to_thread(
            static_cache.compress_and_cache,
            full_path,
            stat_result.st_mtime,
            stat_result.st_size,
            path_obj.read_bytes,
        )
    headers = dict(response.headers)
    headers["content-encoding"] = "gzip"
    headers["content-length"] = str(len(compressed))
    return Response(content=compressed, status_code=200, headers=headers,
                     media_type=response.media_type)


def warm_static_gzip_cache(
    root: Path,
    suffixes: tuple[str, ...],
    *,
    only_files: tuple[str, ...] | None = None,
    skip_dev: bool = True,
) -> int:
    entries = []
    if only_files is not None:
        candidates = [root / rel for rel in only_files]
    else:
        candidates = list(root.rglob("*"))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if not candidate.name.lower().endswith(suffixes):
            continue
        if only_files is None and skip_dev:
            try:
                rel_posix = candidate.relative_to(root).as_posix()
            except ValueError:
                rel_posix = ""
            if _is_dev_bundle(rel_posix):
                continue
        try:
            stat_result = candidate.stat()
        except OSError:
            continue
        entries.append((
            str(candidate),
            stat_result.st_mtime,
            stat_result.st_size,
            candidate.read_bytes,
        ))
    return static_cache.warm(entries)


def render_compressible_html_response(
    request: Request,
    render: Callable[[], str],
    source_path: Path,
    cache_key: str,
    fingerprint: Callable[[str], tuple[float, int]] | None = None,
) -> Response:
    html = render()
    headers = {"Cache-Control": "no-cache, must-revalidate", "Vary": "Accept-Encoding"}
    accept_encoding = request.headers.get("accept-encoding", "")
    if "gzip" in accept_encoding:
        if fingerprint is not None:
            stamp: tuple[float, int] | None = fingerprint(html)
        else:
            try:
                stat_result = source_path.stat()
                stamp = (stat_result.st_mtime, stat_result.st_size)
            except OSError:
                stamp = None
        if stamp is not None:
            compressed = static_cache.peek(cache_key, stamp[0], stamp[1])
            if compressed is None:
                compressed = static_cache.compress_and_cache(
                    cache_key, stamp[0], stamp[1],
                    lambda: html.encode("utf-8"),
                )
            headers["Content-Encoding"] = "gzip"
            headers["Content-Length"] = str(len(compressed))
            return Response(content=compressed, media_type="text/html", headers=headers)
    return HTMLResponse(content=html, headers=headers)


def keyed_page_response(path: str, scope: dict, client_dir: Path) -> Response | None:
    if path not in static_asset_keys.KEYED_PAGE_NAMES:
        return None
    source = client_dir / path
    try:
        source.stat()
    except OSError:
        return None
    return render_compressible_html_response(
        Request(scope),
        lambda: static_asset_keys.render(source.read_text(encoding="utf-8"), client_dir),
        source,
        f"{path}:rendered",
        fingerprint=static_asset_keys.shell_fingerprint,
    )
