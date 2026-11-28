
from __future__ import annotations

import json
import re
from typing import Callable, Optional, Tuple

from src.core.argent.codex_words import AUTH_ENV, BASE_ENV  # noqa: F401
from src.core.argent.codex_words import AUTH_DELIVERY, BASE_DELIVERY  # noqa: F401
from src.core.sessions import codex_update

HEADER_ENV = "CARNIVORE_GATEWAY_CODEX_KEY"
PROVIDER_ID = "argent"
CODEX_PATH = "/chatgpt/backend-api/codex"
TOKEN_PATH = "/v1"
MIN_VERSION: Tuple[int, int, int] = (0, 165, 0)
UNSUPPORTED_REASON = "codex headers unsupported"


def _toml(value: str) -> str:
    return json.dumps(value)


def headers_supported(finder: Callable[[], Optional[str]] = codex_update.find_installed_codex) -> bool:
    version = codex_update.installed_codex_version(finder)
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "")
    return bool(match) and tuple(int(g) for g in match.groups()) >= MIN_VERSION


def flags() -> Tuple[str, ...]:
    base = f"model_providers.{PROVIDER_ID}"
    pairs = (("model_provider", _toml(PROVIDER_ID)), (f"{base}.name", _toml(PROVIDER_ID)),
             (f"{base}.base_url", '"${' + BASE_ENV + '}"'), (f"{base}.requires_openai_auth", "${" + AUTH_ENV + "}"),
             (f"{base}.wire_api", _toml("responses")), (f"{base}.env_http_headers", "{" + f'"x-api-key" = {_toml(HEADER_ENV)}' + "}"))
    return tuple(w for key, value in pairs for w in ("-c", f"{key}={value}"))
