
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from src.core.byoai.contracts import (
    AUTH_BEARER, AUTH_NONE, AUTH_X_API_KEY, CAP_CHAT, PROTO_ANTHROPIC_MESSAGES, PROTO_OPENAI_RESPONSES, Connection,
)
from src.core.byoai.presets import auth_style, default_base_url, enabled_capabilities, get_preset
from src.core.byoai.transport import key_origin

CLAUDE_MANAGED_ENV = (
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_OAUTH_TOKEN",
    "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL",
)

NO_KEY_PLACEHOLDER = "carnivore"

_ENV_SAFE = re.compile(r"[^A-Z0-9]+")


class EndpointRefused(ValueError):
    pass


class ConnectionMissing(EndpointRefused):
    pass


class OriginMismatch(EndpointRefused):
    pass


class KeyNotStored(EndpointRefused):
    pass


class UnsupportedEndpoint(EndpointRefused):
    pass


@dataclass(frozen=True)
class EndpointLaunch:

    env_set: Tuple[Tuple[str, str], ...]
    env_unset: Tuple[str, ...]
    secret_refs: Tuple[Tuple[str, str], ...]
    flags: Tuple[str, ...]
    model: str
    label: str
    key_hint: str


def strip_v1(url: str) -> str:
    base = url.strip().rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def codex_provider_id(connection_id: str) -> str:
    return f"carnivore-{connection_id}"


def codex_key_variable(connection_id: str) -> str:
    return f"CARNIVORE_{_ENV_SAFE.sub('_', connection_id.upper()).strip('_')}_API_KEY"


def _toml(value: str) -> str:
    return json.dumps(value)


def _url(connection: Connection) -> str:
    url = (connection.base_url or default_base_url(get_preset(connection.preset), connection.options)).strip()
    if not url:
        raise EndpointRefused(f"connection {connection.id} has no base url")
    return url


def _key_state(connection: Connection, url: str) -> bool:
    preset = get_preset(connection.preset)
    if not connection.key_host:
        if preset.key_required:
            raise KeyNotStored(f"connection {connection.id} needs a key and none is stored")
        return False
    if connection.key_host != key_origin(url):
        raise OriginMismatch(f"connection {connection.id} has its key bound to {connection.key_host}, not {key_origin(url)}")
    return True


def _require_chat_protocol(connection: Connection, protocol: str, harness: str) -> None:
    preset = get_preset(connection.preset)
    if CAP_CHAT not in enabled_capabilities(preset, connection.options) or protocol not in preset.capabilities.get(CAP_CHAT, ()):
        raise UnsupportedEndpoint(f"{preset.id} does not speak {protocol}, which {harness} needs")
    picked = connection.options.get("protocol")
    if preset.custom and picked and picked != protocol:
        raise UnsupportedEndpoint(f"connection {connection.id} speaks {picked}, and {harness} needs {protocol}")


def endpoint_launch(harness: str, connection: Optional[Connection], model: Optional[str],
                    connection_id: str = "") -> EndpointLaunch:
    if harness not in ("claude", "codex"):
        raise UnsupportedEndpoint(f"a {harness} launch cannot use a connection")
    if connection is None or not connection.enabled:
        raise ConnectionMissing(f"connection {connection.id if connection else connection_id!r} is not configured or is switched off")
    if not (model or "").strip():
        raise EndpointRefused(f"a launch on connection {connection.id} needs a model")
    model = str(model).strip()
    url = _url(connection)
    has_key = _key_state(connection, url)
    style = auth_style(get_preset(connection.preset), connection.options)
    label = connection.label or connection.id
    hint = connection.key_hint[-4:] if has_key else ""
    if harness == "claude":
        return _claude(connection, url, model, has_key, style, label, hint)
    return _codex(connection, url, model, has_key, style, label, hint)


def _claude(connection: Connection, url: str, model: str, has_key: bool, style: str, label: str, hint: str) -> EndpointLaunch:
    _require_chat_protocol(connection, PROTO_ANTHROPIC_MESSAGES, "claude")
    if style not in (AUTH_BEARER, AUTH_X_API_KEY, AUTH_NONE):
        raise UnsupportedEndpoint(f"claude cannot send the {style} auth style")
    env = [("ANTHROPIC_BASE_URL", strip_v1(url))]
    secrets = []
    if style == AUTH_X_API_KEY and has_key:
        secrets.append(("ANTHROPIC_API_KEY", connection.id))
    else:
        env.append(("ANTHROPIC_API_KEY", ""))
        if has_key and style == AUTH_BEARER:
            secrets.append(("ANTHROPIC_AUTH_TOKEN", connection.id))
        else:
            env.append(("ANTHROPIC_AUTH_TOKEN", NO_KEY_PLACEHOLDER))
    env += [(f"ANTHROPIC_DEFAULT_{tier}_MODEL", model) for tier in ("OPUS", "SONNET", "HAIKU")]
    env.append(("CLAUDE_CODE_SUBAGENT_MODEL", model))
    owned = {n for n, _ in env} | {n for n, _ in secrets}
    return EndpointLaunch(tuple(env), tuple(n for n in CLAUDE_MANAGED_ENV if n not in owned), tuple(secrets), (), model, label, hint)


def _codex(connection: Connection, url: str, model: str, has_key: bool, style: str, label: str, hint: str) -> EndpointLaunch:
    _require_chat_protocol(connection, PROTO_OPENAI_RESPONSES, "codex")
    if style not in (AUTH_BEARER, AUTH_NONE):
        raise UnsupportedEndpoint(f"codex sends its key as a bearer token, not {style}")
    pid = codex_provider_id(connection.id)
    key_var = codex_key_variable(connection.id)
    settings = [("model_provider", _toml(pid)), (f"model_providers.{pid}.name", _toml(label)),
                (f"model_providers.{pid}.base_url", _toml(url.rstrip("/"))),
                (f"model_providers.{pid}.wire_api", _toml("responses"))]
    secrets: Tuple[Tuple[str, str], ...] = ()
    env: Tuple[Tuple[str, str], ...] = ()
    if has_key:
        settings.append((f"model_providers.{pid}.env_key", _toml(key_var)))
        secrets = ((key_var, connection.id),)
    flags = tuple(w for key, value in settings for w in ("-c", f"{key}={value}"))
    return EndpointLaunch(env, (), secrets, flags, model, label, hint)
