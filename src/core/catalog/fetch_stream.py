
from __future__ import annotations

import re
import ssl
import zlib
from dataclasses import dataclass
from typing import Optional, Tuple, Union

import httpx
import structlog

logger = structlog.get_logger()


INDEX_UNAVAILABLE = "index_unavailable"

TLS_VERIFY_FAILED = "tls_verify_failed"

_IDENTITY_HEADERS = {"Accept-Encoding": "identity"}

_GZIP_WBITS = 16 + zlib.MAX_WBITS

_ENTITY_TAG = re.compile(r'^(?:W/)?"[\x21\x23-\x7E]*"$')

_CLOSED_CLIENT_MARKER = "closed"


@dataclass(frozen=True)
class FetchRefusal:

    code: str
    detail: str


def refuse(code: str, detail: str, **context: object) -> FetchRefusal:
    logger.warning("catalog_fetch_refused", code=code, detail=detail, **context)
    return FetchRefusal(code=code, detail=detail)


def is_tls_verification_failure(exc: BaseException) -> bool:
    seen: set = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _classify_transport_error(exc: httpx.RequestError, url_kind: str) -> FetchRefusal:
    if isinstance(exc, httpx.TimeoutException):
        return refuse(
            INDEX_UNAVAILABLE,
            f"timed out fetching the {url_kind}",
            document=url_kind,
        )
    if is_tls_verification_failure(exc):
        return refuse(
            TLS_VERIFY_FAILED,
            (
                f"tls verification failed fetching the {url_kind}; "
                "this client verifies against certifi, not the macOS keychain"
            ),
            document=url_kind,
        )
    return refuse(
        INDEX_UNAVAILABLE,
        f"could not connect to fetch the {url_kind}: {exc}",
        document=url_kind,
    )


def _classify_request_failure(exc: Exception, url_kind: str) -> FetchRefusal:
    cause = exc
    if isinstance(exc, ExceptionGroup) and exc.exceptions:
        cause = exc.exceptions[0]
    return refuse(
        INDEX_UNAVAILABLE,
        f"the {url_kind} url could not be requested ({type(cause).__name__})",
        document=url_kind,
    )


def _usable_etag(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if _ENTITY_TAG.match(value):
        return value
    logger.warning("catalog_etag_refused", length=len(value))
    return None


def _status_refusal(status: int, url_kind: str) -> Optional[FetchRefusal]:
    if status == 200:
        return None
    if 300 <= status < 400:
        return refuse(
            INDEX_UNAVAILABLE, "redirect refused", status=status, document=url_kind
        )
    if status == 404:
        return refuse(
            INDEX_UNAVAILABLE,
            f"the {url_kind} was not found (404)",
            status=status,
            document=url_kind,
        )
    if status >= 500:
        return refuse(
            INDEX_UNAVAILABLE,
            f"the host answered {status} for the {url_kind}",
            status=status,
            document=url_kind,
        )
    return refuse(
        INDEX_UNAVAILABLE,
        f"unexpected status {status} for the {url_kind}",
        status=status,
        document=url_kind,
    )


async def _read_capped(response: httpx.Response, limit: int) -> Optional[bytes]:
    chunks: list = []
    total = 0
    async for chunk in response.aiter_raw():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_body(
    raw: bytes, encoding: str, limit: int, url_kind: str
) -> Union[bytes, FetchRefusal]:
    label = encoding.strip().lower()
    if label in ("", "identity"):
        return raw

    if label == "gzip":
        decompressor = zlib.decompressobj(_GZIP_WBITS)
    elif label == "deflate":
        decompressor = zlib.decompressobj()
    else:
        return refuse(
            INDEX_UNAVAILABLE,
            f"the {url_kind} arrived in an unsupported content encoding",
            encoding=label,
            document=url_kind,
        )

    try:
        decoded = decompressor.decompress(raw, limit)
    except zlib.error as exc:
        return refuse(
            INDEX_UNAVAILABLE,
            f"the {url_kind} could not be decompressed: {exc}",
            document=url_kind,
        )
    if decompressor.unconsumed_tail or not decompressor.eof:
        return refuse(
            INDEX_UNAVAILABLE,
            (
                f"the {url_kind} decompressed past the {limit} byte cap; "
                "refused mid-stream"
            ),
            document=url_kind,
        )
    return decoded


async def fetch_document(
    client: httpx.AsyncClient,
    url: str,
    *,
    limit: int,
    url_kind: str,
    extra_headers: Optional[dict] = None,
) -> Union[Tuple[int, bytes, Optional[str]], FetchRefusal]:
    headers = dict(_IDENTITY_HEADERS)
    if extra_headers:
        headers.update(extra_headers)

    try:
        async with client.stream("GET", url, headers=headers) as response:
            etag = _usable_etag(response.headers.get("ETag"))
            if response.status_code == 304:
                return 304, b"", etag
            status_refusal = _status_refusal(response.status_code, url_kind)
            if status_refusal is not None:
                return status_refusal
            raw = await _read_capped(response, limit)
            if raw is None:
                return refuse(
                    INDEX_UNAVAILABLE,
                    (
                        f"the {url_kind} exceeded the {limit} byte cap; "
                        "refused mid-stream"
                    ),
                    document=url_kind,
                )
            encoding = response.headers.get("Content-Encoding", "")
    except httpx.RequestError as exc:
        return _classify_transport_error(exc, url_kind)
    except RuntimeError as exc:
        if _CLOSED_CLIENT_MARKER not in str(exc).lower():
            raise
        return refuse(
            INDEX_UNAVAILABLE,
            f"the http client was closed before the {url_kind} was fetched",
            document=url_kind,
        )
    except (httpx.InvalidURL, ValueError, ExceptionGroup) as exc:
        return _classify_request_failure(exc, url_kind)

    decoded = _decode_body(raw, encoding, limit, url_kind)
    if isinstance(decoded, FetchRefusal):
        return decoded
    return 200, decoded, etag
