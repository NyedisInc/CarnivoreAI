
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Optional, Set, Union
from urllib.parse import urlsplit, urlunsplit

import httpx
import structlog

from src.core.catalog.fetch_stream import FetchRefusal, fetch_document, refuse
from src.core.catalog.verify_types import VerifiedIndex
from src.models.catalog_media import MEDIA_SHA_RE

logger = structlog.get_logger()

MAX_MEDIA_BYTES = 1024 * 1024

MEDIA_INVALID = "media_invalid"

_STORE_DIR = "catalog-media"
_STORE_NAME_RE = re.compile(r"^[0-9a-f]{64}\.webp$")


def referenced_shas(verified: Optional[VerifiedIndex]) -> Set[str]:
    if verified is None:
        return set()
    found: Set[str] = set()
    for item in (*verified.items, *verified.untrusted_items):
        media = item.card.media
        if media is not None:
            found.add(media.sha256)
    return found


def media_url(index_url: str, sha256: str) -> str:
    parts = urlsplit(index_url)
    directory = parts.path.rsplit("/", 1)[0]
    return urlunsplit(
        parts._replace(path=f"{directory}/media/{sha256}.webp", query="", fragment="")
    )


def is_webp(body: bytes) -> bool:
    return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"


async def fetch_media(
    client: httpx.AsyncClient, index_url: str, sha256: str
) -> Union[bytes, FetchRefusal]:
    result = await fetch_document(
        client, media_url(index_url, sha256), limit=MAX_MEDIA_BYTES, url_kind="media"
    )
    if isinstance(result, FetchRefusal):
        return result
    _status, body, _etag = result
    if hashlib.sha256(body).hexdigest() != sha256:
        return refuse(MEDIA_INVALID, "the image bytes do not hash to the named sha256")
    if not is_webp(body):
        return refuse(MEDIA_INVALID, "the image bytes are not a webp container")
    return body


def store_path(state_dir: Path, sha256: str) -> Path:
    if not MEDIA_SHA_RE.match(sha256):
        raise ValueError("not a sha256")
    return state_dir / _STORE_DIR / f"{sha256}.webp"


def save_media(state_dir: Path, sha256: str, body: bytes, keep: Set[str]) -> None:
    target = store_path(state_dir, sha256)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    for entry in target.parent.iterdir():
        if _STORE_NAME_RE.match(entry.name) and entry.name[:-5] not in keep:
            try:
                entry.unlink()
            except OSError as exc:
                logger.warning("catalog_media_prune_failed", error=str(exc))
