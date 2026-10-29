
from __future__ import annotations

import json
import re
from typing import Any, Dict

from src.core.message_model_secrets import scan_text

EXTRA_BODY_OPTION = "extra_body"

MAX_EXTRA_BODY_CHARS = 4096

RESERVED_FIELDS = frozenset({"model", "messages", "stream", "stream_options"})

_SECRET_NAMES = frozenset({
    "key", "token", "auth", "apikey", "xapikey", "accesstoken", "refreshtoken", "idtoken",
    "sessiontoken", "authtoken", "bearer", "pass",
})

_SECRET_FRAGMENTS = ("apikey", "secret", "password", "passwd", "authorization", "credential",
                     "cookie", "privatekey", "accesstoken", "refreshtoken", "authtoken")

_AUTH_SCHEME = re.compile(r"^\s*(bearer|basic|token)\s+\S", re.I)


class ExtraBodyError(ValueError):
    pass


def secretish_name(name: str) -> bool:
    flat = re.sub(r"[^a-z0-9]", "", name.lower())
    return flat in _SECRET_NAMES or any(part in flat for part in _SECRET_FRAGMENTS)


def _check_tree(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for name, item in value.items():
            if secretish_name(str(name)):
                raise ExtraBodyError(f"field {path}{name!s} looks like a secret; keys live in the Keychain")
            _check_tree(item, f"{path}{name!s}.")
    elif isinstance(value, list):
        for item in value:
            _check_tree(item, path)
    elif isinstance(value, str) and (_AUTH_SCHEME.match(value) or scan_text(value)):
        raise ExtraBodyError(f"a value under {path.rstrip('.') or 'the object'} looks like a credential")


def parse_extra_body(text: Any) -> Dict[str, Any]:
    if text is None or (isinstance(text, str) and not text.strip()):
        return {}
    if not isinstance(text, str):
        raise ExtraBodyError("extra request fields must be json text")
    if len(text) > MAX_EXTRA_BODY_CHARS:
        raise ExtraBodyError(f"extra request fields are longer than {MAX_EXTRA_BODY_CHARS} characters")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ExtraBodyError("extra request fields are not valid json") from None
    if not isinstance(data, dict):
        raise ExtraBodyError("extra request fields must be a json object")
    reserved = sorted(RESERVED_FIELDS.intersection(data))
    if reserved:
        raise ExtraBodyError(f"extra request fields may not set {', '.join(reserved)}")
    _check_tree(data, "")
    return data
