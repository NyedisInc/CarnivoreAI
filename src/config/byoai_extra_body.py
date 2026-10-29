"""Per-connection extra request body fields for the OpenAI chat wire (Task Manager 50).

A connection may carry ``options["extra_body"]``: a JSON OBJECT, stored as its
JSON TEXT, merged into every ``/chat/completions`` body sent to that connection.
The worked example is vLLM serving a reasoning model whose output is only
usable with thinking off::

    {"chat_template_kwargs": {"enable_thinking": false}}

Why the text lives in ``options`` as a string rather than as a new field: the
byoai block is ``extra="forbid"`` and options accept scalars only, so an older
build reading a config that carries this option still loads the whole block
(a string option passes its validator). That is the downgrade-safety argument
and the reason no ``config_version`` bump goes with it.

NEVER A SECRET: a name that looks like a credential (``authorization``,
``api_key``, ``token``, ...) is refused at ANY depth, as is a string value that
looks like one, because config.json is not the Keychain. The fields the wire
itself owns (``model``, ``messages``, ``stream``, ``stream_options``) are
refused too, so the box cannot break the call it rides on.
"""

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
