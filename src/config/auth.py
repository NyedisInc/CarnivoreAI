
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from src.core import auth_defaults

from src.config.agents import AgentsConfig
from src.config.browser import BrowserConfig
from src.config.byoai import ByoaiConfig
from src.config.launch_profiles import LaunchProfilesConfig
from src.config.mcp import McpConfig
from src.config.catalog import CatalogConfig
from src.config.provider_accounts import ProviderAccountsConfig
from src.config.relay import RelayConfig
from src.config.providers import ProvidersConfig
from src.config.rate_limits import AuthRateLimits
from src.config.session import SessionConfig
from src.config.swarm_switch import SwarmSwitchConfig
from src.config.ui import UIConfig
from src.config.uploads import UploadsConfig
from src.config.workspace import ServerPrefsConfig, WorkspaceConfig


class AuthConfig(BaseModel):
    """Authentication configuration loaded from JSON and .env."""
    config_version: int = auth_defaults.CONFIG_VERSION
    totp_secret: Optional[str] = None
    jwt_secret: Optional[str] = None
    jwt_expiry_minutes: int = auth_defaults.JWT_EXPIRY_MINUTES
    access_token_ttl_seconds: int = auth_defaults.ACCESS_TOKEN_TTL_SECONDS
    refresh_token_ttl_seconds: int = auth_defaults.REFRESH_TOKEN_TTL_SECONDS
    refresh_grace_seconds: int = auth_defaults.REFRESH_GRACE_SECONDS
    template_path: Optional[str] = None
    common_slash_commands: List[Union[str, Dict[str, Any]]] = []
    session: SessionConfig = Field(default_factory=SessionConfig)
    auth_rate_limits: AuthRateLimits = Field(default_factory=AuthRateLimits)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    uploads: UploadsConfig = Field(default_factory=UploadsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    server_prefs: ServerPrefsConfig = Field(default_factory=ServerPrefsConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)
    provider_accounts: ProviderAccountsConfig = Field(
        default_factory=ProviderAccountsConfig
    )
    relay: RelayConfig = Field(default_factory=RelayConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    swarm_switch: SwarmSwitchConfig = Field(default_factory=SwarmSwitchConfig)
    byoai: ByoaiConfig = Field(default_factory=ByoaiConfig)
    launch_profiles: LaunchProfilesConfig = Field(default_factory=LaunchProfilesConfig)
