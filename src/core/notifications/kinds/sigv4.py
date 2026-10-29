
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional
from urllib.parse import parse_qsl, quote

ALGORITHM = "AWS4-HMAC-SHA256"
_SAFE = "-_.~"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _canonical_query(query: str) -> str:
    pairs = parse_qsl(query, keep_blank_values=True)
    enc = sorted((quote(k, safe=_SAFE), quote(v, safe=_SAFE)) for k, v in pairs)
    return "&".join(f"{k}={v}" for k, v in enc)


def _norm_value(value: str) -> str:
    return " ".join(value.strip().split())


def canonical_request(
    *,
    method: str,
    path: str,
    query: str,
    headers: Mapping[str, str],
    payload: bytes,
) -> tuple[str, str]:
    items = sorted((k.strip().lower(), _norm_value(v)) for k, v in headers.items())
    canon_headers = "".join(f"{k}:{v}\n" for k, v in items)
    signed = ";".join(k for k, _ in items)
    canon_path = quote(path or "/", safe="/" + _SAFE)
    creq = "\n".join(
        [
            method.upper(),
            canon_path,
            _canonical_query(query),
            canon_headers,
            signed,
            _sha256_hex(payload),
        ]
    )
    return creq, signed


def signing_key(secret_key: str, date: str, region: str, service: str) -> bytes:
    k = _hmac(("AWS4" + secret_key).encode("utf-8"), date)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def sign_v4(
    *,
    method: str,
    host: str,
    path: str = "/",
    query: str = "",
    headers: Optional[Mapping[str, str]] = None,
    body: bytes = b"",
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    session_token: Optional[str] = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, str]:
    now = clock().astimezone(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = amz_date[:8]
    out: dict[str, str] = dict(headers or {})
    out["Host"] = host
    out["X-Amz-Date"] = amz_date
    if session_token:
        out["X-Amz-Security-Token"] = session_token
    creq, signed = canonical_request(
        method=method, path=path, query=query, headers=out, payload=body
    )
    scope = f"{date}/{region}/{service}/aws4_request"
    sts = "\n".join([ALGORITHM, amz_date, scope, _sha256_hex(creq.encode("utf-8"))])
    key = signing_key(secret_key, date, region, service)
    sig = hmac.new(key, sts.encode("utf-8"), hashlib.sha256).hexdigest()
    out["Authorization"] = (
        f"{ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={signed}, Signature={sig}"
    )
    return out
