
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

import structlog

from src.core.catalog.client import _ensure_client
from src.core.catalog.fetch_stream import (
    INDEX_UNAVAILABLE,
    FetchRefusal,
    fetch_document,
    refuse,
)
from src.models.catalog import ItemVersion

logger = structlog.get_logger()

CODELOAD_BASE_URL = "https://codeload.github.com"

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024

_DOT_SEGMENTS = frozenset({".", ".."})


def _refuse_source(repo: str, commit: str) -> Optional[FetchRefusal]:
    if not REPO_RE.fullmatch(repo):
        return refuse(
            INDEX_UNAVAILABLE,
            "the version's repository is not an owner/name pair",
            document="archive",
        )
    if any(segment in _DOT_SEGMENTS for segment in repo.split("/")):
        return refuse(
            INDEX_UNAVAILABLE,
            "the version's repository carries a dot path segment",
            document="archive",
        )
    if not COMMIT_RE.fullmatch(commit):
        return refuse(
            INDEX_UNAVAILABLE,
            "the version's source commit is not a full lowercase sha",
            document="archive",
        )
    return None


def archive_url(repo: str, commit: str) -> Union[str, FetchRefusal]:
    refusal = _refuse_source(repo, commit)
    if refusal is not None:
        return refusal
    return f"{CODELOAD_BASE_URL}/{repo}/tar.gz/{commit}"


async def fetch_archive(
    version: ItemVersion,
    *,
    dest_path: Path,
    max_bytes: int = MAX_ARCHIVE_BYTES,
) -> Union[Path, FetchRefusal]:
    url = archive_url(version.src.repo, version.src.commit)
    if isinstance(url, FetchRefusal):
        logger.warning("catalog_archive_source_refused", detail=url.detail)
        return url

    client = await _ensure_client()
    result = await fetch_document(
        client, url, limit=max_bytes, url_kind="archive"
    )
    if isinstance(result, FetchRefusal):
        logger.warning("catalog_archive_fetch_refused", code=result.code)
        return result

    _status, body, _etag = result
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(body)
    logger.info(
        "catalog_archive_fetched", bytes=len(body), commit=version.src.commit
    )
    return dest_path
