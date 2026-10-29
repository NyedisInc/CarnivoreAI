"""``Settings``: the loader, and the typed readers over it.

**EVERY PUBLIC NAME AND EVERY SIGNATURE IS UNCHANGED, AND THAT IS A HARD
CONSTRAINT RATHER THAN POLITENESS.** 111 modules import from this
package, and the suite patches these members on the CLASS - 23 sites do
``monkeypatch.setattr(settings, "state_dir_override", ...)``, eight do
``monkeypatch.setattr(type(sm.settings), "get_state_dir", ...)``. A
method that stopped resolving here would be invisible to every one of
them.

**THE TWO CACHES LIVE HERE BECAUSE THE CONFIGURATION THAT KEYS THEM DOES.**
``_auth_config_cache`` is invalidated by every writer in this package,
which is why the writers are called from here rather than reached
directly: a caller that wrote config.json through
:mod:`src.config.config_writes` without coming past this object would
leave a stale parse in memory. ``_state_file_pins`` is keyed on the
CONFIGURED directories, so repointing one re-asks the question while a
file appearing or disappearing does not.

**LAZINESS IS PRESERVED WHERE IT WAS LOAD-BEARING.**
:func:`~src.config.agent_command.agent_command` takes CALLABLES for the
state directory and the alternate-screen setting rather than values,
because resolving the first can raise and reading the second must happen
at launch time. See that module's docstring.
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional

import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field, field_validator

from src.core.product_identity import env_names, env_value
from src.config import (
    agent_command as _agent_command,
    auth_loader as _auth_loader,
    config_writes as _config_writes,
    mcp_launch,
    provider_models as _provider_models,
    state_paths as _state_paths,
    summary as _summary,
    wrappers as _wrappers,
)
from src.config.agents import AgentsConfig
from src.core.agent_families import RESERVED_FAMILY_NAMES
from src.config.auth import AuthConfig
from src.config.session import SessionConfig
from src.core.byoai.contracts import to_connection
from src.core.agent_wrappers import AgentWrapper
from src.core import wrapper_store

_logger = structlog.get_logger()


OLD_DEFAULT_WORKING_DIR = "~/cloude-projects"
NEW_DEFAULT_WORKING_DIR = "~/carnivore-projects"


def migrate_default_working_dir(value: str) -> str:
    stripped = value.strip().rstrip("/")
    old_forms = {OLD_DEFAULT_WORKING_DIR, str(Path(OLD_DEFAULT_WORKING_DIR).expanduser())}
    return NEW_DEFAULT_WORKING_DIR if stripped in old_forms else value


class Settings(BaseSettings):
    """Application configuration settings."""

    model_config = SettingsConfigDict(
        env_file=env_value("SETTINGS_ENV_FILE") or ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    host: str = "0.0.0.0"
    port: int = 8000
    dev_reload: bool = Field(
        default=False,
        validation_alias=AliasChoices(*env_names("DEV_RELOAD")),
    )

    ledger_keepalive: bool = Field(
        default=True,
        validation_alias=AliasChoices(*env_names("LEDGER_KEEPALIVE")),
    )

    default_working_dir: str = Field(default=NEW_DEFAULT_WORKING_DIR, validate_default=True)
    session_timeout: int = 3600

    @field_validator("default_working_dir", mode="after")
    @classmethod
    def _migrate_default_working_dir(cls, value: str) -> str:
        return migrate_default_working_dir(value)

    log_buffer_size: int = 1000
    log_file_retention: int = 7
    log_level: str = "INFO"
    cloude_debug: str = Field(
        default="",
        validation_alias=AliasChoices(*env_names("DEBUG")),
    )
    dev_shape_alerts: bool = Field(
        default=False,
        validation_alias=AliasChoices(*env_names("DEV_SHAPE_ALERTS")),
    )
    dev_perf_hooks: bool = Field(
        default=False,
        validation_alias=AliasChoices(*env_names("DEV_PERF_HOOKS")),
    )
    log_directory: Optional[str] = None

    state_dir_override: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(*env_names("STATE_DIR")),
    )

    api_key: Optional[str] = None
    allowed_origins_override: Optional[str] = Field(
        default=None,
        alias="ALLOWED_ORIGINS",
        description=(
            "Comma-separated CORS origin override. When set, replaces the "
            "computed default wholesale. Leave unset to use the safe "
            "HOST/PORT + hostname-derived default."
        ),
    )

    allowed_hosts_extra: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(*env_names("ALLOWED_HOSTS")),
        description=(
            "Comma-separated extra Host names (exact or *.suffix) added to "
            "the built-in allowlist. '*' disables the Host check."
        ),
    )

    totp_secret: Optional[str] = None
    jwt_secret: Optional[str] = None

    auth_config_file: str = "./config.json"

    claude_cli_path: Optional[str] = None

    _auth_config_cache: Optional[AuthConfig] = None

    _state_file_pins: Optional[dict] = None


    @property
    def allowed_origins(self) -> List[str]:
        return _state_paths.allowed_origins(
            self.allowed_origins_override, self.host, self.port
        )


    def get_working_dir(self) -> Path:
        return _state_paths.working_dir(self.default_working_dir)

    def get_state_dir(self) -> Path:
        """The durable state directory, resolved and ensured.

        Inputs: none (reads ``state_dir_override``).
        Output: Path - existing and writable.
        Raises:
            StateDirUnavailableError: it could not be created.
        """
        return _state_paths.state_dir(self.state_dir_override)

    def state_dir_is_explicit(self) -> bool:
        """Did the operator NAME a state directory (``CLOUDE_STATE_DIR``)?

        Description: the rule lives in
          :func:`src.config.state_paths.state_dir_is_explicit`; this is
          the seam. An explicit state directory suppresses the legacy
          ``log_directory`` pin, which is what makes that one variable
          enough to isolate a dev or test instance (issue #113).
        Inputs: none (reads ``state_dir_override``).
        Output: bool.
        """
        return _state_paths.state_dir_is_explicit(self.state_dir_override)

    def get_log_dir(self) -> Path:
        return self.get_state_dir()

    def _state_file_pin(self, filename: str) -> tuple:
        if self._state_file_pins is None:
            self._state_file_pins = {}
        return _state_paths.state_file_pin(
            filename,
            pins=self._state_file_pins,
            resolved_state_dir=self.get_state_dir(),
            state_dir_override=self.state_dir_override,
            log_directory=self.log_directory,
            state_dir_explicit=self.state_dir_is_explicit(),
        )

    def get_state_file_location(self, filename: str) -> str:
        return self._state_file_pin(filename)[1]

    def _resolve_state_file(self, filename: str) -> Path:
        return self._state_file_pin(filename)[0]

    def get_refresh_tokens_path(self) -> Path:
        """The refresh-token revocation database, through the pin.

        Description: the pin is what gives it the old ``log_directory``
          fallback. Without one, an install predating the state directory
          got a BRAND NEW EMPTY database on its next start and abandoned
          every issued refresh token. A file one directory over is not a
          file being gone.
        Inputs: none.
        Output: Path.
        """
        return self._resolve_state_file("refresh_tokens.db")

    def get_session_metadata_path(self) -> Path:
        return self._resolve_state_file("session_metadata.json")

    def get_pinned_themes_path(self) -> Path:
        return self._resolve_state_file("pinned_themes.json")

    def get_session_backgrounds_path(self) -> Path:
        return self._resolve_state_file("session_backgrounds.json")

    def get_session_background_images_dir(self) -> Path:
        return self.get_session_backgrounds_path().parent / "session_backgrounds"

    def get_unread_state_path(self) -> Path:
        return self._resolve_state_file("unread_state.json")


    def get_claude_cli_path(self) -> str:
        return _agent_command.claude_cli_path(self.claude_cli_path)

    def get_agent_command(
        self,
        agent_type: Optional[str],
        model: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
        *,
        model_is_explicit: bool = False,
        pane_launch: bool = False,
        plan_sink: Optional[list] = None,
        purpose: str = "pane",
    ) -> str:
        auth = None
        try:
            auth = self.load_auth_config()
            agents = auth.agents
            session_cfg = auth.session
            mcp_on = auth.mcp.enabled
            channel_on = auth.mcp.channels
        except Exception:  # noqa: BLE001
            agents = AgentsConfig()
            session_cfg = SessionConfig()
            mcp_on = False
            channel_on = False
        block = getattr(auth, "launch_profiles", None)
        profiles = tuple(block.profiles) if block is not None else None
        byoai = getattr(auth, "byoai", None)
        connections = tuple(to_connection(c) for c in byoai.connections) if byoai is not None else ()
        return _agent_command.agent_command(
            agent_type,
            agents=agents,
            resolve_state_dir=lambda: str(self.get_state_dir()),
            disable_alternate_screen=lambda: session_cfg.disable_alternate_screen,
            model=model,
            model_is_explicit=model_is_explicit,
            extra_args=extra_args,
            carnivore_mcp_url=mcp_launch.registration_url(
                pane_launch, mcp_on, self.port),
            carnivore_mcp_channel=channel_on,
            profiles=profiles,
            connections=connections,
            plan_sink=plan_sink,
            purpose=purpose,
        )

    def pane_launch_command(
        self,
        agent_type: Optional[str],
        model: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
        *,
        model_is_explicit: bool = False,
        plan_sink: Optional[list] = None,
    ) -> str:
        """THE ONE builder of a session pane's launch command, Carnivore MCP registration included (#1726).

        Description: every path that starts an agent in a pane (create, wake and recreate, restart and respawn
          with or without a picked wrapper, the bridge migration's restart) and every check or preview of what
          such a path would run (``session_agent_choice``, the restart preview) renders through here, so the
          inline ``--mcp-config`` stdio bridge entry and the channel flag (``mcp_launch.claude_args``) are on
          every one of them or on none. Before #1726 the registration hung on a per-call ``pane_launch`` flag
          that defaulted off, and the wrapper validator, whose command a picked-wrapper restart RUNS, never set
          it: that restart came back with no carnivore server, and the wake and restart answers showed a
          command without it. ``tests/python/launch_wrappers/test_bridge_on_every_launch.py`` refuses a second call site.
        Inputs: agent_type (str | None); model (str | None); extra_args (list[str] | None) - the resume, name
          and fork arguments, quoted by the builder, never concatenated; model_is_explicit (bool); plan_sink
          (list | None) - as :meth:`get_agent_command`.
        Output: str - one shell string for tmux.
        Raises: ValueError - as :meth:`get_agent_command`.
        Example: settings.pane_launch_command("claude", extra_args=["--resume", uuid])
        """
        return self.get_agent_command(
            agent_type, model=model, extra_args=extra_args, model_is_explicit=model_is_explicit,
            pane_launch=True, plan_sink=plan_sink,
        )

    def get_launch_profiles(self) -> tuple:
        """The configured launch profiles (the loaded config's ``launch_profiles`` block).

        Output: tuple[LaunchProfile, ...] - ``()`` when config.json cannot be read or has no block.
        Example: [p.id for p in settings.get_launch_profiles()]
        """
        try:
            block = getattr(self.load_auth_config(), "launch_profiles", None)
        except (OSError, ValueError) as exc:
            structlog.get_logger().warning("launch_profiles_unreadable", error=str(exc))
            return ()
        return tuple(block.profiles) if block is not None else ()


    def drop_auth_config_cache(self) -> None:
        self._auth_config_cache = None

    def load_auth_config(self) -> AuthConfig:
        if self._auth_config_cache is not None:
            return self._auth_config_cache
        auth_config = _auth_loader.load(
            Path(self.auth_config_file).expanduser(),
            totp_secret=self.totp_secret,
            jwt_secret=self.jwt_secret,
        )
        self._auth_config_cache = auth_config
        return auth_config


    def get_catalog_index_url(self) -> str:
        return self.load_auth_config().catalog.index_url

    def get_catalog_api_base_url(self) -> str:
        return self.load_auth_config().catalog.api_base_url


    def get_provider_models(self) -> List[str]:
        return list(self.load_auth_config().providers.models)

    def add_provider_model(self, model: str) -> List[str]:
        models = _provider_models.add(
            Path(self.auth_config_file).expanduser(), model
        )
        self._auth_config_cache = None
        return models

    def remove_provider_model(self, model: str) -> List[str]:
        models = _provider_models.remove(
            Path(self.auth_config_file).expanduser(), model
        )
        self._auth_config_cache = None
        return models


    def _family_summaries(self, agents: AgentsConfig) -> List[dict]:
        return _summary.family_summaries(agents, self.get_agent_command)

    def get_settings_summary(self) -> dict:
        from src.core.setup_state import recorded_bound_host  # noqa: PLC0415

        config = self.load_auth_config()
        return _summary.settings_summary(
            config,
            host=self.host,
            port=self.port,
            families=self._family_summaries(config.agents),
            bound_host=recorded_bound_host(),
        )

    def update_settings_config(
        self,
        workspace_update: Optional[dict] = None,
        server_prefs_update: Optional[dict] = None,
    ) -> dict:
        _config_writes.update_settings_config(
            Path(self.auth_config_file).expanduser(),
            workspace_update=workspace_update,
            server_prefs_update=server_prefs_update,
        )
        self._auth_config_cache = None
        return self.get_settings_summary()


    def _read_config_dict(self, config_path: Path) -> dict:
        from src.config.config_file import read_config  # noqa: PLC0415

        return read_config(config_path)

    def _mutate_wrappers(
        self, mutation: Callable[[List[dict]], List[dict]]
    ) -> List[dict]:
        updated = _wrappers.mutate(
            Path(self.auth_config_file).expanduser(), mutation
        )
        self._auth_config_cache = None
        return updated

    def ensure_wrapper_defaults(self) -> bool:
        try:
            wrote = _wrappers.ensure_defaults(Path(self.auth_config_file).expanduser())
        except FileNotFoundError:
            return False
        except (ValueError, OSError) as exc:
            _logger.warning("wrapper_defaults_not_written", error=str(exc))
            return False
        if wrote:
            self._auth_config_cache = None
            _logger.info("wrapper_defaults_seeded")
        return wrote

    def add_wrapper(self, wrapper: AgentWrapper) -> List[dict]:
        return self._mutate_wrappers(
            lambda ws: wrapper_store.add(
                ws, wrapper.model_dump(), RESERVED_FAMILY_NAMES
            )
        )

    def update_wrapper(self, wrapper_id: str, wrapper: AgentWrapper) -> List[dict]:
        replacement = wrapper.model_dump(
            exclude={k for k in wrapper_store.KEPT_WHEN_ABSENT if k not in wrapper.model_fields_set}
        )
        return self._mutate_wrappers(
            lambda ws: wrapper_store.update(ws, wrapper_id, replacement)
        )

    def set_wrapper_icon(self, wrapper_id: str, icon: Optional[str]) -> List[dict]:
        return self._mutate_wrappers(
            lambda ws: wrapper_store.set_icon(ws, wrapper_id, icon)
        )

    def delete_wrapper(self, wrapper_id: str) -> List[dict]:
        return self._mutate_wrappers(lambda ws: wrapper_store.delete(ws, wrapper_id))

    def set_default_wrapper(self, wrapper_id: str) -> List[dict]:
        return self._mutate_wrappers(
            lambda ws: wrapper_store.set_default(ws, wrapper_id)
        )

