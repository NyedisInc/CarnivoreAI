
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

import structlog
from pydantic import BaseModel, TypeAdapter, ValidationError

from src.config.agents import AgentsConfig
from src.config.auth import AuthConfig
from src.config.browser import BROWSER_KEY, BrowserConfig
from src.config.byoai import BYOAI_KEY, ByoaiConfig
from src.config.launch_profiles import LAUNCH_PROFILES_KEY, LaunchProfilesConfig
from src.config.mcp import MCP_KEY, McpConfig
from src.config.provider_accounts import (
    PROVIDER_ACCOUNTS_KEY,
    ProviderAccountsConfig,
)
from src.config.providers import ProvidersConfig
from src.config.rate_limits import AuthRateLimits
from src.config.relay import RELAY_KEY, RelayConfig
from src.config.swarm_switch import SWARM_SWITCH_KEY, SwarmSwitchConfig
from src.config.session import SessionConfig
from src.config.ui import UI_KEY, UIConfig
from src.config.uploads import UploadsConfig
from src.config.workspace import ServerPrefsConfig, WorkspaceConfig
from src.core.launch_profiles.seed_from_wrappers import seed_launch_profiles
from src.core.launch_profiles.wrapper_view import wrappers_from_profiles
from src.core.workspace_settings import SERVER_PREFS_KEY, WORKSPACE_KEY

logger = structlog.get_logger()

BlockT = TypeVar("BlockT", bound=BaseModel)

DEFAULT_JWT_EXPIRY_MINUTES = 30
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 14400
DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 604800
DEFAULT_REFRESH_GRACE_SECONDS = 10


def _raw_payload(raw: Any) -> Dict[str, Any]:
    return {"raw": raw}


def _keys_only_payload(raw: Any) -> Dict[str, Any]:
    return {"keys": sorted(raw.keys()) if isinstance(raw, dict) else None}


def parse_block(
    model: Type[BlockT],
    raw: Any,
    *,
    event: str,
    payload: Callable[[Any], Dict[str, Any]] = _raw_payload,
) -> BlockT:
    try:
        return model(**raw)
    except Exception:  # noqa: BLE001
        logger.warning(event, **payload(raw))
        return model()


def _launch_view(data: Dict[str, Any]) -> tuple:
    stored = parse_block(AgentsConfig, data.get("agents", {}) or {}, event="invalid_agents_config_block")
    raw = data.get(LAUNCH_PROFILES_KEY)
    if raw is not None:
        try:
            block = LaunchProfilesConfig.model_validate(raw)
            return block, AgentsConfig(wrappers=wrappers_from_profiles(block.profiles))
        except ValidationError:
            logger.warning("invalid_launch_profiles_config_block")
    try:
        seeded = seed_launch_profiles({k: v for k, v in data.items() if k != LAUNCH_PROFILES_KEY})
        return LaunchProfilesConfig.model_validate(seeded[LAUNCH_PROFILES_KEY]), stored
    except (ValidationError, KeyError, ValueError):
        logger.warning("launch_profiles_seed_failed")
        return LaunchProfilesConfig(), stored


def _mcp_block(raw: Any) -> McpConfig:
    if not raw:
        return McpConfig()
    try:
        return McpConfig(**raw)
    except Exception:  # noqa: BLE001
        logger.warning("invalid_mcp_config_block")
        return McpConfig(enabled=False)


def _relay_switched_off(raw: Any) -> bool:
    value = raw.get("enabled") if isinstance(raw, dict) else raw
    if value is None:
        return False
    try:
        return TypeAdapter(bool).validate_python(value) is False
    except ValidationError:
        return True


def _relay_block(raw: Any) -> RelayConfig:
    killed = _relay_switched_off(raw)
    relay = parse_block(
        RelayConfig, raw or {}, event="invalid_relay_config_block",
        payload=_keys_only_payload,
    )
    return relay.model_copy(update={"enabled": False}) if killed else relay


def load(
    config_path: Path, *, totp_secret: Optional[str], jwt_secret: Optional[str]
) -> AuthConfig:
    """Load authentication configuration from JSON plus the .env secrets.

    Description: non-secrets come from the JSON file, the two secrets
      come from the environment through ``Settings``. A legacy
      ``projects`` key is deliberately NOT read - projects live in
      ``cloude.db`` only.
    Inputs: config_path (Path) - the expanded ``config.json`` path;
      totp_secret (str | None) and jwt_secret (str | None) - from .env.
    Output: AuthConfig.
    Raises:
        FileNotFoundError: the file does not exist.
        ValueError: the file is not valid JSON, or a secret is missing.
    Example: load(Path("~/config.json").expanduser(), totp_secret=t, jwt_secret=j)
    """
    if not config_path.exists():
        raise FileNotFoundError(
            f"Auth config file not found: {config_path}\n"
            f"Run ./setup_auth.py to create it."
        )

    try:
        with open(config_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Invalid JSON in auth config file: {e}\n"
            f"Check {config_path}"
        )

    config_version = data.get("config_version", 0)
    if not isinstance(config_version, int):
        config_version = 0

    launch_view = _launch_view(data)
    auth_config = AuthConfig(
        config_version=config_version,
        totp_secret=totp_secret,
        jwt_secret=jwt_secret,
        jwt_expiry_minutes=data.get(
            "jwt_expiry_minutes", DEFAULT_JWT_EXPIRY_MINUTES
        ),
        access_token_ttl_seconds=int(
            data.get("access_token_ttl_seconds", DEFAULT_ACCESS_TOKEN_TTL_SECONDS)
        ),
        refresh_token_ttl_seconds=int(
            data.get("refresh_token_ttl_seconds", DEFAULT_REFRESH_TOKEN_TTL_SECONDS)
        ),
        refresh_grace_seconds=int(
            data.get("refresh_grace_seconds", DEFAULT_REFRESH_GRACE_SECONDS)
        ),
        template_path=data.get("template_path"),
        common_slash_commands=data.get("common_slash_commands", []),
        session=parse_block(
            SessionConfig, data.get("session", {}) or {},
            event="invalid_session_config_block",
        ),
        auth_rate_limits=parse_block(
            AuthRateLimits, data.get("auth_rate_limits", {}) or {},
            event="invalid_auth_rate_limits_block",
        ),
        agents=launch_view[1],
        launch_profiles=launch_view[0],
        uploads=parse_block(
            UploadsConfig, data.get("uploads", {}) or {},
            event="invalid_uploads_config_block",
        ),
        providers=parse_block(
            ProvidersConfig, data.get("providers", {}) or {},
            event="invalid_providers_config_block",
        ),
        workspace=parse_block(
            WorkspaceConfig, data.get(WORKSPACE_KEY, {}) or {},
            event="invalid_workspace_config_block",
            payload=_keys_only_payload,
        ),
        server_prefs=parse_block(
            ServerPrefsConfig, data.get(SERVER_PREFS_KEY, {}) or {},
            event="invalid_server_prefs_config_block",
        ),
        ui=parse_block(
            UIConfig, data.get(UI_KEY, {}) or {},
            event="invalid_ui_config_block",
        ),
        provider_accounts=parse_block(
            ProviderAccountsConfig, data.get(PROVIDER_ACCOUNTS_KEY, {}) or {},
            event="invalid_provider_accounts_config_block",
            payload=_keys_only_payload,
        ),
        relay=_relay_block(data.get(RELAY_KEY)),
        browser=parse_block(
            BrowserConfig, data.get(BROWSER_KEY, {}) or {},
            event="invalid_browser_config_block",
        ),
        mcp=_mcp_block(data.get(MCP_KEY)),
        swarm_switch=parse_block(
            SwarmSwitchConfig, data.get(SWARM_SWITCH_KEY, {}) or {},
            event="invalid_swarm_switch_config_block",
        ),
        byoai=parse_block(
            ByoaiConfig, data.get(BYOAI_KEY, {}) or {},
            event="invalid_byoai_config_block",
            payload=_keys_only_payload,
        ),
    )

    if not auth_config.totp_secret or not auth_config.jwt_secret:
        raise ValueError(
            "Missing authentication secrets in .env file.\n"
            "Required: TOTP_SECRET and JWT_SECRET\n"
            "Run ./setup_auth.py to generate them."
        )

    return auth_config
