
from __future__ import annotations

import json
import re
import shlex
from typing import Tuple

from src.core.argent import overlay_codex
from src.core.argent.overlay import SECRET_NAME, _read_key
from src.core.argent.upstream import UPSTREAM_KEY_HEADER, UPSTREAM_URL_HEADER
from src.core.launch_profiles.endpoints import NO_KEY_PLACEHOLDER
from src.core.sessions.launch_overlay import UpstreamRoute

UPSTREAM_URL_ENV = "CARNIVORE_ARGENT_UPSTREAM_URL"
_NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")


def claude_preamble(gateway_url: str, ca_path: str, key_env: str) -> str:
    if key_env and not _NAME.match(key_env):
        raise ValueError("key_env must be a variable name")
    ca = f"export NODE_EXTRA_CA_CERTS={shlex.quote(ca_path)}; " if ca_path else ""
    pk = f'_pk="${{{key_env}-}}"; ' if key_env else '_pk=""; '
    return (
        _read_key() +
        f'if [ -n "$_ak" ] && [ "$_ak" != "-" ]; then {pk}_up="${{ANTHROPIC_BASE_URL-}}"; '
        f'_h="x-api-key: $_ak"$\'\\n\'"{UPSTREAM_URL_HEADER}: $_up"; '
        f'[ -n "$_pk" ] && _h="$_h"$\'\\n\'"{UPSTREAM_KEY_HEADER}: $_pk"; '
        f'export ANTHROPIC_BASE_URL={shlex.quote(gateway_url)}; {ca}export ANTHROPIC_CUSTOM_HEADERS="$_h"; '
        f'export ANTHROPIC_AUTH_TOKEN={shlex.quote(NO_KEY_PLACEHOLDER)}; export ANTHROPIC_API_KEY=; fi; '
        f'unset _ak _pk _up _h _i'
    )


def codex_preamble(ca_path: str, upstream_url: str) -> str:
    ca = f"export CODEX_CA_CERTIFICATE={shlex.quote(ca_path)}; " if ca_path else ""
    return (
        _read_key() +
        f'if [ -n "$_ak" ] && [ "$_ak" != "-" ]; then {ca}export {overlay_codex.HEADER_ENV}="$_ak"; '
        f'export {UPSTREAM_URL_ENV}={shlex.quote(upstream_url)}; fi; unset _ak _i'
    )


def codex_flags(gateway_url: str, route: UpstreamRoute) -> Tuple[str, ...]:
    base_key = next(w.split("=", 1)[0] for w in route.flags if w.split("=", 1)[0].endswith(".base_url"))
    prefix = base_key[:-len("base_url")]
    headers = {"x-api-key": overlay_codex.HEADER_ENV, UPSTREAM_URL_HEADER: UPSTREAM_URL_ENV, **({UPSTREAM_KEY_HEADER: route.key_env} if route.key_env else {})}
    toml = "{" + ", ".join(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in headers.items()) + "}"
    kept = [w for w in route.flags if w != "-c" and not w.startswith((base_key + "=", prefix + "env_http_headers="))]
    return tuple(x for w in (*kept, f"{base_key}={json.dumps(gateway_url.rstrip('/'))}", f"{prefix}env_http_headers={toml}") for x in ("-c", w))
