
from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.config.mcp_launch import CLAUDE_MCP_CONFIG_FLAG
from src.core.agent_wrappers import WRAPPER_ID_PATTERN
from src.core.debug_trace import is_secret_name

LAUNCH_PROFILES_KEY = "launch_profiles"

HARNESSES = ("claude", "codex", "shell", "hermes", "openclaw", "local")
STRUCTURED_HARNESSES = frozenset({"claude", "codex", "shell"})

_ID = re.compile(WRAPPER_ID_PATTERN)
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

_APP_FLAGS = frozenset({
    "--resume", "-r", "--continue", "--name", "-n", "--fork-session", "--session-id",
    CLAUDE_MCP_CONFIG_FLAG,
})
_MODEL_FLAGS = frozenset({"--model", "-m", "--fallback-model", "--oss", "--local-provider"})
_PERMISSION_FLAGS = frozenset({
    "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "--permission-mode",
    "--yolo", "--full-auto", "--dangerously-bypass-approvals-and-sandbox",
    "--ask-for-approval", "-a", "--sandbox", "-s",
})
_OWNED_CONFIG_KEYS = ("mcp_servers", "model", "model_provider", "model_providers", "approval_policy", "sandbox_mode")


def _refusal(flag: str) -> Optional[str]:
    name = flag.split("=", 1)[0]
    if name in _APP_FLAGS:
        return f"{name} is added by the app on every launch"
    if name in _MODEL_FLAGS:
        return f"{name} belongs to the model field"
    if name in _PERMISSION_FLAGS:
        return f"{name} belongs to the permissions field"
    return None


def _config_key_refusal(setting: str) -> Optional[str]:
    key = setting.split("=", 1)[0].strip().split(".", 1)[0]
    return f"-c {key} is owned by the app or another field" if key in _OWNED_CONFIG_KEYS else None


class AccountRef(BaseModel):
    """Which provider account a launch uses: follow the active one, or pin one (claude only)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["follow_active", "pinned"] = "follow_active"
    account_id: Optional[str] = None

    @model_validator(mode="after")
    def _pin_names_an_account(self) -> "AccountRef":
        if (self.mode == "pinned") != bool(self.account_id):
            raise ValueError("a pinned account needs account_id, and follow_active takes none")
        return self


class EndpointRef(BaseModel):
    """Where the model is served: the harness's own endpoint, or one BYOAI connection."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["native", "connection"] = "native"
    connection_id: Optional[str] = None

    @model_validator(mode="after")
    def _connection_names_one(self) -> "EndpointRef":
        if (self.mode == "connection") != bool(self.connection_id):
            raise ValueError("a connection endpoint needs connection_id, and native takes none")
        return self


class ModelRef(BaseModel):
    """Which model: the harness default, one fixed id, or ask at launch."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["default", "fixed", "ask"] = "default"
    value: Optional[str] = None

    @model_validator(mode="after")
    def _fixed_has_a_value(self) -> "ModelRef":
        if (self.mode == "fixed") != bool(self.value):
            raise ValueError("a fixed model needs value, and default or ask take none")
        return self


class EnvRow(BaseModel):
    """One plain environment variable. A secret-looking name is refused: it must be a secret row."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: str = ""

    @field_validator("name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        if not _ENV_NAME.fullmatch(value):
            raise ValueError("env name must be letters, digits and _ and not start with a digit")
        if is_secret_name(value):
            raise ValueError(f"{value} reads like a secret; add it as a secret row")
        return value

    @field_validator("value")
    @classmethod
    def _one_line(cls, value: str) -> str:
        if _CONTROL.search(value):
            raise ValueError("env value must not contain control characters")
        return value


class SecretRow(BaseModel):
    """One secret variable: its name and the Keychain item that holds it. Never the value."""

    model_config = ConfigDict(extra="forbid")

    name: str
    keychain_ref: str

    @field_validator("name")
    @classmethod
    def _secret_name(cls, value: str) -> str:
        if not _ENV_NAME.fullmatch(value):
            raise ValueError("secret name must be letters, digits and _ and not start with a digit")
        if not is_secret_name(value):
            raise ValueError(f"{value} does not read like a secret, so a trace would not redact it; rename it")
        return value

    @field_validator("keychain_ref")
    @classmethod
    def _a_reference(cls, value: str) -> str:
        if not value.strip() or len(value) > 200 or _CONTROL.search(value):
            raise ValueError("keychain_ref must be a short single-line Keychain item reference")
        return value


class CustomCommand(BaseModel):
    """The expert mode: a zsh script (and optional entry function), run as a wrapper runs today."""

    model_config = ConfigDict(extra="forbid")

    script: str
    entry: Optional[str] = None


class LaunchProfile(BaseModel):
    """One launch profile. ``id`` equals the id of the wrapper it replaces, so stored sessions keep resolving."""

    model_config = ConfigDict(extra="forbid")

    id: str
    harness: Literal["claude", "codex", "shell", "hermes", "openclaw", "local"]
    label: str = Field(min_length=1)
    icon: Optional[str] = None
    description: Optional[str] = None
    default: bool = False
    account: AccountRef = Field(default_factory=AccountRef)
    endpoint: EndpointRef = Field(default_factory=EndpointRef)
    model: ModelRef = Field(default_factory=ModelRef)
    permissions: Literal["harness_default", "ask", "accept_edits", "skip_all"] = "harness_default"
    flags: List[str] = Field(default_factory=list)
    env: List[EnvRow] = Field(default_factory=list)
    secrets: List[SecretRow] = Field(default_factory=list)
    shell_profile: bool = True
    before_launch: Optional[str] = None
    custom_command: Optional[CustomCommand] = None
    custom_command_ack_no_args: bool = False

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not _ID.fullmatch(value):
            raise ValueError(f"id must match {WRAPPER_ID_PATTERN}")
        return value

    @field_validator("flags")
    @classmethod
    def _flags_are_the_profiles_to_set(cls, flags: List[str]) -> List[str]:
        previous = ""
        for token in flags:
            if not token or _CONTROL.search(token):
                raise ValueError("a flag must be a non-empty single-line token")
            is_option = token.startswith("-")
            if not is_option and not previous.startswith("-"):
                raise ValueError(f"{token!r} is not a flag or the value of one")
            reason = _refusal(token) if is_option else None
            if previous in ("-c", "--config") and not is_option:
                reason = _config_key_refusal(token)
            elif is_option and token.split("=", 1)[0] in ("-c", "--config") and "=" in token:
                reason = _config_key_refusal(token.split("=", 1)[1])
            if reason:
                raise ValueError(reason)
            previous = token if is_option and "=" not in token else ""
        return flags

    @model_validator(mode="after")
    def _cross_field_rules(self) -> "LaunchProfile":
        if self.account.mode == "pinned" and self.harness != "claude":
            raise ValueError("an account can be pinned only for claude")
        if self.harness not in STRUCTURED_HARNESSES:
            if self.custom_command is None:
                raise ValueError(f"a {self.harness} profile needs a custom command")
            if (self.permissions != "harness_default" or self.flags or self.endpoint.mode != "native"
                    or self.model.mode == "fixed"):
                raise ValueError(f"a {self.harness} profile cannot use structured permissions, flags, endpoint or a fixed model")
        cmd = self.custom_command
        if cmd is not None and not self.custom_command_ack_no_args:
            if '"$@"' not in cmd.script and not (cmd.entry or "").strip():
                raise ValueError('the script does not forward "$@", so resume, name and MCP args would be dropped; '
                                 "forward them or acknowledge it")
        names = [row.name for row in (*self.env, *self.secrets)]
        if len(names) != len(set(names)):
            raise ValueError("a variable name appears twice across env and secrets")
        return self


class LaunchProfilesConfig(BaseModel):
    """The whole block. ``revision`` counts writes; a stale write is refused. One default per harness."""

    model_config = ConfigDict(extra="forbid")

    revision: int = 0
    profiles: List[LaunchProfile] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids_and_defaults(self) -> "LaunchProfilesConfig":
        ids = [p.id for p in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("launch profile ids must be unique")
        defaults = [p.harness for p in self.profiles if p.default]
        if len(defaults) != len(set(defaults)):
            raise ValueError("a harness can have only one default launch profile")
        return self
