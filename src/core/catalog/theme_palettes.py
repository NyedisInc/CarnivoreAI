
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import weakref
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import structlog
from fastapi import HTTPException

from src.core.skills.validate_types import ArchiveRefused
from src.models.catalog import CatalogItem, ItemVersion
from src.models.catalog_theme_palettes import ThemePaletteEntry

logger = structlog.get_logger()

MAX_CONCURRENT_READS = 2
BUDGET_SECONDS = 2.0

CSS_VAR_KEYS: Tuple[str, ...] = (
    "--color-bg-page", "--color-bg", "--color-bg-card", "--color-bg-elevated",
    "--color-fg", "--color-accent", "--color-header-bg", "--color-border",
    "--color-border-subtle", "--color-fg-faint", "--color-fg-muted",
    "--color-fg-subtle", "--color-success", "--color-warning", "--color-danger",
)
XTERM_KEYS: Tuple[str, ...] = (
    "background", "foreground", "cursor",
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "brightBlack", "brightRed", "brightGreen", "brightYellow",
    "brightBlue", "brightMagenta", "brightCyan", "brightWhite",
)

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB = re.compile(r"^rgba?\(\s*[0-9.,%\s]+\)$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_VALUE_CHARS = 64

_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)
_inflight: Dict[str, "asyncio.Task[Optional[ThemePaletteEntry]]"] = {}

MAX_REFUSED = 512
_refused: Set[str] = set()
_serial: Optional[int] = None
_pruned_serial: Optional[int] = None

ReadView = Callable[[CatalogItem, ItemVersion], Awaitable[Any]]


def is_safe_colour(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > _MAX_VALUE_CHARS:
        return False
    return bool(_HEX.match(text) or _RGB.match(text))


def _safe_map(source: Any, keys: Tuple[str, ...]) -> Dict[str, str]:
    if not isinstance(source, dict):
        return {}
    return {k: source[k].strip() for k in keys if is_safe_colour(source.get(k))}


def reduce_manifest(text: str, digest: str, version: str) -> Optional[ThemePaletteEntry]:
    try:
        manifest = json.loads(text)
    except ValueError:
        return None
    if not isinstance(manifest, dict):
        return None
    raw_vars = manifest.get("cssVars")
    css_vars = _safe_map(raw_vars, CSS_VAR_KEYS)
    xterm = _safe_map(manifest.get("xterm"), XTERM_KEYS)
    if not css_vars and not xterm:
        return None
    ascii_on = isinstance(raw_vars, dict) and raw_vars.get("--ascii-display") == "block"
    return ThemePaletteEntry(
        digest=digest, version=version, cssVars=css_vars, xterm=xterm, ascii=ascii_on
    )


def _cache_file(cache_dir: Path, digest: str) -> Optional[Path]:
    return cache_dir / f"{digest}.json" if _DIGEST.match(digest) else None


def _read_cache(cache_dir: Path, digest: str) -> Optional[ThemePaletteEntry]:
    path = _cache_file(cache_dir, digest)
    if path is None or not path.is_file():
        return None
    try:
        entry = ThemePaletteEntry.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if entry.digest != digest:
        return None
    if _safe_map(entry.cssVars, CSS_VAR_KEYS) != entry.cssVars:
        return None
    if _safe_map(entry.xterm, XTERM_KEYS) != entry.xterm or not (entry.cssVars or entry.xterm):
        return None
    return entry


def _prune_cache(cache_dir: Path, live: Set[str]) -> None:
    try:
        files = list(cache_dir.glob("*.json"))
    except OSError as exc:
        logger.warning("catalog_theme_palette_prune_failed", error=type(exc).__name__)
        return
    for path in files:
        if path.stem in live:
            continue
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("catalog_theme_palette_prune_failed", error=type(exc).__name__)


def _note_serial(serial: int) -> bool:
    global _serial, _pruned_serial
    if serial != _serial:
        _serial = serial
        _refused.clear()
    if _pruned_serial == serial:
        return False
    _pruned_serial = serial
    return True


def _refuse(digest: str) -> None:
    if len(_refused) < MAX_REFUSED:
        _refused.add(digest)


def _write_cache(cache_dir: Path, entry: ThemePaletteEntry) -> None:
    path = _cache_file(cache_dir, entry.digest)
    if path is None:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json())
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("catalog_theme_palette_cache_write_failed", error=type(exc).__name__)


def _gate() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(MAX_CONCURRENT_READS)
    return gate


class _Busy(Exception):
    pass


async def _derive(
    item: CatalogItem, version: ItemVersion, read_view: ReadView, cache_dir: Path
) -> Optional[ThemePaletteEntry]:
    async with _gate():
        cached = _read_cache(cache_dir, version.digest)
        if cached is not None:
            return cached
        try:
            view = await read_view(item, version)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if detail.get("code") == "staging_busy" or exc.status_code >= 500:
                raise _Busy() from exc
            logger.warning(
                "catalog_theme_palette_refused", item_id=item.id, code=detail.get("code")
            )
            _refuse(version.digest)
            return None
        except ArchiveRefused as exc:
            logger.warning(
                "catalog_theme_palette_refused", item_id=item.id, digest=version.digest, code=exc.code
            )
            _refuse(version.digest)
            return None
    if view.digest != version.digest:
        logger.warning("catalog_theme_palette_digest_differs", item_id=item.id)
        _refuse(version.digest)
        return None
    entry = reduce_manifest(view.manifest_text, version.digest, version.v)
    if entry is None:
        logger.warning("catalog_theme_palette_unreadable", item_id=item.id)
        _refuse(version.digest)
        return None
    await asyncio.to_thread(_write_cache, cache_dir, entry)
    return entry


async def _derive_shared(
    item: CatalogItem, version: ItemVersion, read_view: ReadView, cache_dir: Path
) -> Optional[ThemePaletteEntry]:
    task = _inflight.get(version.digest)
    if task is None:
        task = asyncio.ensure_future(_derive(item, version, read_view, cache_dir))
        _inflight[version.digest] = task
        task.add_done_callback(lambda _t, d=version.digest: _inflight.pop(d, None))
    return await asyncio.shield(task)


async def derive_palettes(
    themes: List[Tuple[CatalogItem, ItemVersion]],
    read_view: ReadView,
    cache_dir: Path,
    serial: int,
    budget: float = BUDGET_SECONDS,
) -> Tuple[Dict[str, ThemePaletteEntry], List[str]]:
    results: Dict[str, ThemePaletteEntry] = {}
    pending: List[str] = []
    cold: List[Tuple[CatalogItem, "asyncio.Future[Optional[ThemePaletteEntry]]"]] = []
    if _note_serial(serial):
        live = {version.digest for _, version in themes}
        await asyncio.to_thread(_prune_cache, cache_dir, live)
    for item, version in themes:
        cached = await asyncio.to_thread(_read_cache, cache_dir, version.digest)
        if cached is not None:
            results[item.id] = cached
            continue
        if version.digest in _refused:
            continue
        cold.append((item, asyncio.ensure_future(_derive_shared(item, version, read_view, cache_dir))))
    if cold:
        await asyncio.wait([f for _, f in cold], timeout=budget)
    version_digests = {item.id: version.digest for item, version in themes}
    for item, future in cold:
        if not future.done():
            pending.append(item.id)
            future.add_done_callback(lambda f: f.cancelled() or f.exception())
            continue
        try:
            entry = future.result()
        except _Busy:
            pending.append(item.id)
            continue
        except (OSError, ValueError) as exc:
            logger.warning(
                "catalog_theme_palette_read_failed",
                item_id=item.id, digest=version_digests[item.id], error=type(exc).__name__,
            )
            continue
        if entry is not None:
            results[item.id] = entry
    return results, pending
