
from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Union
from urllib.parse import urlsplit, urlunsplit

import httpx
import structlog

from src.core.catalog.fetch_stream import (
    INDEX_UNAVAILABLE,
    TLS_VERIFY_FAILED,
    FetchRefusal,
    fetch_document,
    refuse,
)
from src.core.catalog.verify_types import INDEX_NOT_JSON

logger = structlog.get_logger()

__all__ = [
    "DEFAULT_INDEX_URL",
    "DEFAULT_TIMEOUT",
    "INDEX_NOT_JSON",
    "INDEX_UNAVAILABLE",
    "MAX_INDEX_BYTES",
    "MAX_MINISIG_BYTES",
    "TLS_VERIFY_FAILED",
    "FetchRefusal",
    "IndexFetch",
    "counted_fetch",
    "fetch_index",
    "init",
    "minisig_url",
    "read_minisig",
    "refuse_index_url",
    "shared_client",
    "shutdown",
]


DEFAULT_INDEX_URL = "https://catalog.carnivore.ai/v1/index.json"

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

MAX_INDEX_BYTES = 4 * 1024 * 1024

MAX_MINISIG_BYTES = 4 * 1024

_MINISIG_LINES = 4

# already running
_SHUTDOWN_GRACE_SECONDS = 5.0


_client: Optional[httpx.AsyncClient] = None

_client_options: Optional[Dict[str, Any]] = None

_in_flight = 0
_idle = asyncio.Event()
_idle.set()


@contextlib.asynccontextmanager
async def counted_fetch() -> AsyncIterator[None]:
    global _in_flight

    _in_flight += 1
    _idle.clear()
    try:
        yield
    finally:
        _in_flight -= 1
        if _in_flight == 0:
            _idle.set()


@dataclass(frozen=True)
class IndexFetch:

    index_bytes: Optional[bytes]
    minisig_text: Optional[str]
    etag: Optional[str]
    not_modified: bool


async def init(
    *,
    timeout: Optional[httpx.Timeout] = None,
    verify: Any = True,
) -> None:
    """Build the module-level client, closing any previous one.

    Description: idempotent in the strong sense. Asking for the pool that
      is ALREADY BUILT AND OPEN, with the options it was built with, is a
      no-op: the previous version closed and rebuilt unconditionally,
      which meant a second init() pulled the transport out from under
      every fetch already running on the first. A genuine change of
      options still closes the old pool, and that close now waits for
      those fetches. The app itself never calls this with arguments; both
      exist so a test can point the client at a server it started, with
      the timeout it wants and its own certificate authority. NOTHING IN
      THE APP EVER DISABLES VERIFICATION, and ``verify`` is httpx's own
      parameter passed straight through rather than a mode this module
      implements.
    Inputs: timeout (httpx.Timeout | None) - overall and connect budget;
      :data:`DEFAULT_TIMEOUT` when None. verify (Any) - httpx's ``verify``
      argument; True means certifi.
    Output: None.
    Example: await init()
    """
    global _client, _client_options

    options: Dict[str, Any] = {
        "timeout": timeout or DEFAULT_TIMEOUT,
        "verify": verify,
    }
    if _client is not None and not _client.is_closed and _client_options == options:
        return

    if _client is not None:
        await shutdown()

    _client = httpx.AsyncClient(follow_redirects=False, **options)
    _client_options = options
    logger.info("catalog_client_initialized")


async def shutdown() -> None:
    global _client, _client_options

    if _client is None:
        return
    if _in_flight:
        try:
            await asyncio.wait_for(_idle.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("catalog_client_shutdown_impatient", in_flight=_in_flight)

    client, _client, _client_options = _client, None, None
    try:
        await client.aclose()
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        logger.warning("catalog_client_close_error", error=str(exc))
    logger.info("catalog_client_shutdown")


async def _ensure_client() -> httpx.AsyncClient:
    if _client is None:
        await init()
    elif _client.is_closed:
        await init(**(_client_options or {}))
    client = _client
    if client is None:
        raise RuntimeError("the catalog http client failed to initialise")
    return client


async def shared_client() -> httpx.AsyncClient:
    return await _ensure_client()


def minisig_url(index_url: str) -> str:
    parts = urlsplit(index_url)
    return urlunsplit(parts._replace(path=parts.path + ".minisig"))


def refuse_index_url(index_url: str) -> Optional[FetchRefusal]:
    try:
        parts = urlsplit(index_url)
        _ = parts.port
    except ValueError as exc:
        return refuse(
            INDEX_UNAVAILABLE,
            f"index_url could not be parsed: {exc}",
        )
    if parts.scheme != "https":
        return refuse(
            INDEX_UNAVAILABLE,
            "index_url is not https, so it was refused before any request",
        )
    if parts.username is not None or parts.password is not None:
        return refuse(
            INDEX_UNAVAILABLE,
            "userinfo in url, so index_url was refused before any request",
        )
    return None


def read_minisig(body: bytes) -> Union[str, FetchRefusal]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return refuse(INDEX_NOT_JSON, "the signature file is not utf-8")
    lines = text.splitlines()
    if len(lines) != _MINISIG_LINES:
        return refuse(
            INDEX_NOT_JSON,
            f"the signature file has {len(lines)} lines, expected {_MINISIG_LINES}",
        )
    return text


async def fetch_index(
    index_url: str, *, etag: Optional[str]
) -> Union[IndexFetch, FetchRefusal]:
    url_refusal = refuse_index_url(index_url)
    if url_refusal is not None:
        return url_refusal

    client = await _ensure_client()
    conditional = {"If-None-Match": etag} if etag else None
    async with counted_fetch():
        index_result = await fetch_document(
            client,
            index_url,
            limit=MAX_INDEX_BYTES,
            url_kind="index",
            extra_headers=conditional,
        )
        if isinstance(index_result, FetchRefusal):
            return index_result

        status, index_bytes, fetched_etag = index_result
        if status == 304:
            if etag is None:
                return refuse(
                    INDEX_UNAVAILABLE, "304 without a conditional request"
                )
            logger.info("catalog_index_not_modified")
            return IndexFetch(
                index_bytes=None,
                minisig_text=None,
                etag=etag,
                not_modified=True,
            )

        try:
            json.loads(index_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return refuse(INDEX_NOT_JSON, "the index body is not json")

        sig_result = await fetch_document(
            client,
            minisig_url(index_url),
            limit=MAX_MINISIG_BYTES,
            url_kind="minisig",
        )
    if isinstance(sig_result, FetchRefusal):
        return sig_result

    _, sig_bytes, _ = sig_result
    minisig_text = read_minisig(sig_bytes)
    if isinstance(minisig_text, FetchRefusal):
        return minisig_text

    logger.info(
        "catalog_index_fetched",
        bytes=len(index_bytes),
        etag_present=bool(fetched_etag),
    )
    return IndexFetch(
        index_bytes=index_bytes,
        minisig_text=minisig_text,
        etag=fetched_etag,
        not_modified=False,
    )
