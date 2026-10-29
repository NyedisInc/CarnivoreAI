
from __future__ import annotations

import os
import shlex
import unicodedata
from typing import Dict

from src.config.provider_accounts import ProviderAccount, profile_dir_for

__all__ = [
    "login_command_for",
    "login_env_for",
    "login_profile_dir",
    "PROFILE_ENV_VARS",
]

PROFILE_ENV_VARS: Dict[str, str] = {
    "claude": "CLAUDE_CONFIG_DIR",
    "codex": "CODEX_HOME",
}

_LOGIN_COMMANDS: Dict[str, str] = {
    "claude": "command claude auth login",
    "codex": "codex login",
}

_CODEX_DEVICE_LOGIN = "codex login --device-auth"


def _variable_for(account: ProviderAccount) -> str:
    variable = PROFILE_ENV_VARS.get(account.provider)
    if variable is None:
        raise ValueError(f"no login is defined for provider {account.provider!r}")
    return variable


def login_profile_dir(account: ProviderAccount) -> str:
    profile = profile_dir_for(account)
    if account.managed:
        return profile
    return unicodedata.normalize(
        "NFC", os.path.realpath(os.path.expanduser(profile))
    )


def login_env_for(account: ProviderAccount, profile_dir: str) -> Dict[str, str]:
    return {_variable_for(account): profile_dir}


def login_command_for(
    account: ProviderAccount, profile_dir: str, device_auth: bool = False
) -> str:
    variable = _variable_for(account)
    command = _LOGIN_COMMANDS[account.provider]
    if device_auth and account.provider == "codex":
        command = _CODEX_DEVICE_LOGIN
    return f"{variable}={shlex.quote(profile_dir)} {command}"
