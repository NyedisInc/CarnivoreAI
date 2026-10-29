
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx
import structlog

from src.core.catalog.client import shared_client
from src.core.catalog.fetch_stream import is_tls_verification_failure

logger = structlog.get_logger()

__all__ = [
    "DEFAULT_API_BASE_URL",
    "MAX_HOSTED_BYTES",
    "TLS_VERIFY_FAILED",
    "UNAVAILABLE",
    "HostedAnswer",
    "HostedUnavailable",
    "call",
    "refuse_api_base_url",
    "shared_client",
]

DEFAULT_API_BASE_URL = "https://api.carnivore.ai/v1"

MAX_HOSTED_BYTES = 256 * 1024

UNAVAILABLE = "unavailable"

TLS_VERIFY_FAILED = "tls_verify_failed"

_USER_AGENT = "cloude-code"

_MAX_ATTEMPTS = 2

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD"})

_RETRYABLE_ERRORS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)


class HostedUnavailable(Exception):
    """The hosted catalog api could not be reached, or did not answer JSON.

    Attributes:
        code: a short machine readable reason, one of :data:`UNAVAILABLE`
            or :data:`TLS_VERIFY_FAILED`.
        detail: what went wrong, for a log and for a developer. It never
            contains the url, because a url may carry a password.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class HostedAnswer:

    status: int
    body: Dict[str, Any]


def refuse_api_base_url(api_base_url: str) -> Optional[str]:
    try:
        parts = urlsplit(api_base_url)
        _ = parts.port
    except ValueError as exc:
        return f"api_base_url could not be parsed: {exc}"
    if parts.scheme != "https":
        return "api_base_url is not https, so it was refused before any request"
    if parts.username is not None or parts.password is not None:
        return "userinfo in url, so api_base_url was refused before any request"
    if not parts.netloc:
        return "api_base_url names no host, so it was refused before any request"
    return None


async def _read_capped(response: httpx.Response) -> bytes:
    chunks = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_HOSTED_BYTES:
            raise HostedUnavailable(
                UNAVAILABLE,
                f"the catalog api answered with more than the {MAX_HOSTED_BYTES} byte cap",
            )
        chunks.append(chunk)
    return b"".join(chunks)


class _AttemptFailed(Exception):

    def __init__(self, cause: httpx.RequestError, *, response_started: bool) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.response_started = response_started


def _may_retry(method: str, failure: _AttemptFailed) -> bool:
    if method.upper() not in _IDEMPOTENT_METHODS:
        return False
    if failure.response_started:
        return False
    if is_tls_verification_failure(failure.cause):
        return False
    return isinstance(failure.cause, _RETRYABLE_ERRORS)


async def _attempt(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json_body: Optional[Dict[str, Any]],
    headers: Dict[str, str],
) -> tuple[int, bytes]:
    response_started = False
    try:
        async with client.stream(
            method, url, json=json_body, headers=headers
        ) as response:
            response_started = True
            if 300 <= response.status_code < 400:
                raise HostedUnavailable(
                    UNAVAILABLE,
                    f"the catalog api answered {response.status_code} with a redirect",
                )
            return response.status_code, await _read_capped(response)
    except httpx.RequestError as exc:
        raise _AttemptFailed(exc, response_started=response_started) from exc


def _transport_refusal(exc: httpx.RequestError) -> HostedUnavailable:
    if is_tls_verification_failure(exc):
        return HostedUnavailable(
            TLS_VERIFY_FAILED,
            "the certificate the catalog api presented did not verify",
        )
    return HostedUnavailable(UNAVAILABLE, "the catalog api could not be reached")


async def call(
    api_base_url: str,
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    bearer: Optional[str] = None,
) -> HostedAnswer:
    """Make one call to the hosted catalog api and read its answer.

    Description: the url is checked BEFORE the connection pool is even
      reached for, so a misconfigured base tells the network nothing. A
      redirect is refused rather than followed, because following one
      would let the host move an authenticated call somewhere this app
      did not choose. The body is capped while it is read, and anything
      that is not a JSON object is a refusal rather than an answer.

      A TRANSPORT FAILURE IS TRIED ONCE MORE, AND ONLY WHEN THAT CANNOT
      COST ANYTHING: the verb has to be idempotent and the response must
      not have started, which together mean the request was not
      processed and the same one is being sent again rather than a
      second one. See :func:`_may_retry`. A write never reaches that
      question. Whichever attempt is the last one logs
      ``catalog_hosted_call_failed`` before it raises, because a 502 in a
      browser with nothing in the log is how this stayed invisible.
    Inputs: api_base_url (str) - e.g. ``https://host/api/v1``; method
      (str) - an HTTP verb; path (str) - the path under the base, leading
      slash included; json_body (dict | None) - sent as JSON when given,
      and no body at all when None; bearer (str | None) - an access
      token, sent as ``Authorization: Bearer`` only when given. Keyword
      only after ``path``.
    Output: HostedAnswer - the host's own status and parsed body,
      including for every refusal.
    Raises: HostedUnavailable - the host could not be reached on any
      attempt, the url was refused, it redirected, or it did not answer a
      JSON object.
    Example: await call(base, "GET", "/items/a/b/ratings")
    """
    refusal = refuse_api_base_url(api_base_url)
    if refusal is not None:
        raise HostedUnavailable(UNAVAILABLE, refusal)

    url = api_base_url.rstrip("/") + path
    headers = {"accept": "application/json", "user-agent": _USER_AGENT}
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"

    client = await shared_client()
    started_at = time.monotonic()
    attempts = 0
    while True:
        attempts += 1
        try:
            status, raw = await _attempt(
                client, method, url, json_body=json_body, headers=headers
            )
            break
        except _AttemptFailed as failure:
            if attempts < _MAX_ATTEMPTS and _may_retry(method, failure):
                continue
            logger.warning(
                "catalog_hosted_call_failed",
                method=method.upper(),
                path=path,
                error=type(failure.cause).__name__,
                attempts=attempts,
                elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
            )
            raise _transport_refusal(failure.cause) from failure.cause

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HostedUnavailable(
            UNAVAILABLE, "the catalog api answered with something that was not json"
        ) from exc
    if not isinstance(parsed, dict):
        raise HostedUnavailable(
            UNAVAILABLE, "the catalog api answered with something that was not an object"
        )

    logger.info(
        "catalog_hosted_call",
        method=method.upper(),
        path=path,
        status=status,
        authorized=bool(bearer),
    )
    return HostedAnswer(status=status, body=parsed)
