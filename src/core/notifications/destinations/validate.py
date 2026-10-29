
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from src.core.notifications import http, kind_specs

LIST_SEPARATOR = "\n"
MAX_LIST_ITEMS = 20


def split_list(raw: Any) -> list:
    parts = raw.split(LIST_SEPARATOR) if isinstance(raw, str) else (raw or [])
    return [str(p).strip() for p in parts if str(p).strip()]

REQUIRED = "required"
TOO_LONG = "too_long"
BAD_VALUE = "bad_value"
UNKNOWN = "unknown"
HTTPS_REQUIRED = "https_required"
PRIVATE_ADDRESS = "private_address"
PLAIN_HTTP_PUBLIC = "plain_http_public"
REQUIRES_PRIVATE = "requires_allow_private"
NOT_SUPPORTED = "not_supported"

_LOCAL_NAME_SUFFIXES = (".local", ".lan", ".home.arpa", ".localhost")


class InvalidDestination(ValueError):

    def __init__(self, fields: Mapping[str, str]) -> None:
        super().__init__("invalid destination fields: " + ", ".join(sorted(fields)))
        self.fields: Dict[str, str] = dict(fields)


def host_policy(spec: kind_specs.KindSpec) -> http.HostPolicy:
    h = spec.hosts
    return http.HostPolicy(exact=h.exact_hosts, suffixes=h.suffixes, pattern=h.regex, any_host=h.any_host,
                           allow_private=spec.allow_private)


def _private_host(host: str, allow_private: bool) -> bool:
    ip = http.ip_literal(host)
    if ip is None:
        return not allow_private and (host == "localhost" or host.endswith(_LOCAL_NAME_SUFFIXES))
    return not http.address_verdict(ip, allow_private=allow_private)


def _public_literal(host: str) -> bool:
    ip = http.ip_literal(host)
    return ip is not None and http.address_verdict(ip, allow_private=False)


def _url_problem(
    value: str, spec: kind_specs.KindSpec, field: kind_specs.FieldSpec, allow_private: Optional[bool],
    allow_plain_http: bool = False,
) -> Optional[str]:
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        return BAD_VALUE
    plain = parts.scheme == "http"
    if plain and (not spec.allow_private or (allow_private is not None and not (allow_private and allow_plain_http))):
        return HTTPS_REQUIRED
    if not (plain or parts.scheme == "https") or not host or "@" in parts.netloc:
        return BAD_VALUE
    try:
        host = http.normalize_host(host)
        if not http.host_allowed(host, host_policy(spec)):
            return BAD_VALUE
    except http.GuardError:
        return BAD_VALUE
    prefix = spec.hosts.path_prefix
    if prefix and not parts.path.startswith(prefix) and field.name == "url":
        return BAD_VALUE
    if plain and _public_literal(host):
        return PLAIN_HTTP_PUBLIC
    if allow_private is not None and spec.allow_private and _private_host(host, allow_private):
        return BAD_VALUE if allow_private else PRIVATE_ADDRESS
    return None


def _scalar(
    value: Any, field: kind_specs.FieldSpec, spec: kind_specs.KindSpec, allow_private: Optional[bool] = None,
    allow_plain_http: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    if field.type == kind_specs.FIELD_INT:
        if isinstance(value, bool) or not (isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit())):
            return None, BAD_VALUE
        number = int(value)
        return (str(number), None) if 1 <= number <= 65535 else (None, BAD_VALUE)
    if not isinstance(value, str):
        return None, BAD_VALUE
    text = value.strip()
    if len(text) > field.max_len:
        return None, TOO_LONG
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        return None, BAD_VALUE
    if field.type == kind_specs.FIELD_URL:
        problem = _url_problem(text, spec, field, allow_private, allow_plain_http)
        if problem:
            return None, problem
    if field.choices and text not in field.choices:
        return None, BAD_VALUE
    if field.pattern and not re.fullmatch(field.pattern, text):
        return None, BAD_VALUE
    return text, None


def _list(value: Any, field: kind_specs.FieldSpec) -> Tuple[Optional[str], Optional[str]]:
    items = re.split(r"[\n,]", value) if isinstance(value, str) else value
    if not isinstance(items, (list, tuple)):
        return None, BAD_VALUE
    clean = []
    for item in items:
        if not isinstance(item, str):
            return None, BAD_VALUE
        text = item.strip()
        if not text:
            continue
        if len(text) > field.max_len:
            return None, TOO_LONG
        if any(ord(c) < 32 or ord(c) == 127 for c in text) or (field.pattern and not re.fullmatch(field.pattern, text)):
            return None, BAD_VALUE
        clean.append(text)
    if len(clean) > (field.max_items or MAX_LIST_ITEMS):
        return None, TOO_LONG
    return LIST_SEPARATOR.join(clean), None


def validate_fields(
    specs: Tuple[kind_specs.FieldSpec, ...], values: Mapping[str, Any], kind: kind_specs.KindSpec,
    *, existing: Optional[Mapping[str, str]] = None, apply_defaults: bool = True, allow_private: Optional[bool] = None,
    allow_plain_http: bool = False,
) -> Dict[str, str]:
    by_name = {f.name: f for f in specs}
    errors: Dict[str, str] = {name: UNKNOWN for name in values if name not in by_name}
    out: Dict[str, str] = {}
    for field in specs:
        raw = values.get(field.name)
        blank = raw is None or (isinstance(raw, str) and not raw.strip()) or (isinstance(raw, (list, tuple)) and not raw)
        if blank:
            if field.secret and existing is not None and field.name in existing:
                continue
            if field.default is not None and apply_defaults and not field.secret:
                out[field.name] = field.default
            elif field.required and not (existing and field.name in existing):
                errors[field.name] = REQUIRED
            continue
        text, err = _list(raw, field) if field.type == kind_specs.FIELD_LIST else _scalar(raw, field, kind, allow_private, allow_plain_http)
        if err:
            errors[field.name] = err
        elif text == "" and field.required:
            errors[field.name] = REQUIRED
        else:
            out[field.name] = text or ""
    if errors:
        raise InvalidDestination(errors)
    return out


def check_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise InvalidDestination({"name": REQUIRED})
    text = name.strip()
    if len(text) > 64:
        raise InvalidDestination({"name": TOO_LONG})
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise InvalidDestination({"name": BAD_VALUE})
    return text


def typed_config(spec: kind_specs.KindSpec, normalised: Mapping[str, str]) -> Dict[str, Any]:
    ints = {f.name for f in spec.public_fields if f.type == kind_specs.FIELD_INT}
    return {k: (int(v) if k in ints else v) for k, v in normalised.items()}


def check_allow_private(spec: kind_specs.KindSpec, value: Any) -> bool:
    if not isinstance(value, bool):
        raise InvalidDestination({"allow_private": BAD_VALUE})
    if value and not spec.allow_private:
        raise InvalidDestination({"allow_private": NOT_SUPPORTED})
    return value


def check_allow_plain_http(spec: kind_specs.KindSpec, value: Any, allow_private: bool) -> bool:
    if not isinstance(value, bool):
        raise InvalidDestination({"allow_plain_http": BAD_VALUE})
    if value and not spec.allow_private:
        raise InvalidDestination({"allow_plain_http": NOT_SUPPORTED})
    if value and not allow_private:
        raise InvalidDestination({"allow_plain_http": REQUIRES_PRIVATE})
    return value
