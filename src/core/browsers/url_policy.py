
from __future__ import annotations

import ipaddress
import re
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})

ABOUT_BLANK = "about:blank"

MAX_URL_LENGTH = 8192


class UrlRefused(ValueError):
    pass


def _is_loopback_host(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def normalize_url(raw: Optional[str]) -> str:
    text = (raw or "").strip()
    if not text or text == ABOUT_BLANK:
        return ABOUT_BLANK
    if len(text) > MAX_URL_LENGTH:
        raise UrlRefused(f"that address is longer than {MAX_URL_LENGTH} characters")
    if any(ch in text for ch in "\x00\r\n\t"):
        raise UrlRefused("that address carries control characters")
    try:
        return _normalize(text)
    except ValueError as exc:
        if isinstance(exc, UrlRefused):
            raise
        raise UrlRefused("that address could not be parsed") from exc


def _normalize(text: str) -> str:
    parts = urlsplit(text)
    looks_bare = "://" not in text and (
        not parts.scheme or parts.path[:1].isdigit() or "." in parts.scheme
    )
    if looks_bare:
        host = urlsplit("//" + text).hostname or ""
        scheme = "http" if _is_loopback_host(host) else "https"
        parts = urlsplit(f"{scheme}://{text}")
    scheme = parts.scheme
    if scheme not in ALLOWED_SCHEMES:
        raise UrlRefused(
            f"{scheme or 'that'}: addresses are not allowed in a browser "
            "session; only http and https"
        )
    if not parts.hostname:
        raise UrlRefused("that address has no host")
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def is_allowed(url: str) -> bool:
    if url == ABOUT_BLANK:
        return True
    parts = urlsplit(url)
    return parts.scheme in ALLOWED_SCHEMES and bool(parts.hostname)


def origin_of(url: str) -> str:
    if url == ABOUT_BLANK:
        return url
    parts = urlsplit(url)
    try:
        if parts.scheme and parts.hostname:
            port = f":{parts.port}" if parts.port else ""
            return f"{parts.scheme}://{parts.hostname}{port}"
    except ValueError:
        pass
    return "other"


def storable_url(url: str) -> str:
    if not is_allowed(url) or url == ABOUT_BLANK:
        return ABOUT_BLANK
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"[{host}]" if ":" in host else host
    try:
        netloc += f":{parts.port}" if parts.port else ""
    except ValueError:
        return ABOUT_BLANK
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


_NET_ERROR = re.compile(r"net::ERR_[A-Z0-9_]+")


def error_code(exc: BaseException) -> str:
    found = _NET_ERROR.search(str(exc))
    return found.group(0) if found else type(exc).__name__
