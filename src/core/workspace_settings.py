
from __future__ import annotations

import os
import re
import shlex
import shutil
import socket
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.product_identity import ENV_PREFIX, LEGACY_ENV_PREFIXES

WORKSPACE_KEY = "workspace"

SERVER_PREFS_KEY = "server_prefs"

DEV_ROOT_ENV = "CLOUDE_DEV_ROOT"

SHELL_ENV = "SHELL"

ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

RESERVED_ENV_PREFIX = "CLOUDECODE_"

RESERVED_ENV_PREFIXES: Tuple[str, ...] = (ENV_PREFIX,) + LEGACY_ENV_PREFIXES

WARNED_ENV_NAMES = frozenset({"PATH", "HOME", "SHELL", "USER", "LOGNAME", "TMPDIR"})

WARNED_ENV_PREFIXES = ("LD_", "DYLD_", "ANTHROPIC_", "AWS_", "OPENAI_")

_CREDENTIAL_HINTS = ("SECRET", "TOKEN", "PASSWORD", "PASSWD", "APIKEY", "API_KEY")

UNIVERSAL_BIND_HOSTS = ("127.0.0.1", "0.0.0.0")


class WorkspaceValidationError(ValueError):
    pass


def _blank(value: Optional[str]) -> bool:
    return value is None or not str(value).strip()


def validate_development_root(raw: Optional[str]) -> str:
    if _blank(raw):
        return ""
    path = Path(str(raw).strip()).expanduser()
    if not path.exists():
        raise WorkspaceValidationError(
            f"development root does not exist: {path}. Create it first, or "
            "clear the field to leave it unset."
        )
    if not path.is_dir():
        raise WorkspaceValidationError(
            f"development root is not a directory: {path}."
        )
    return str(path)


def validate_shell(raw: Optional[str]) -> str:
    if _blank(raw):
        return ""
    text = str(raw).strip()
    candidate = Path(text).expanduser()
    if candidate.is_absolute() or text.startswith("~") or os.sep in text:
        resolved: Optional[str] = str(candidate) if candidate.exists() else None
    else:
        resolved = shutil.which(text)
    if resolved is None:
        raise WorkspaceValidationError(
            f"shell not found: {text}. Give an absolute path such as "
            "/bin/zsh, or a name that resolves on PATH."
        )
    if not os.access(resolved, os.X_OK):
        raise WorkspaceValidationError(
            f"shell is not executable: {resolved}."
        )
    if Path(resolved).is_dir():
        raise WorkspaceValidationError(f"shell is a directory: {resolved}.")
    return resolved


def validate_editor(raw: Optional[str]) -> str:
    if _blank(raw):
        return ""
    text = str(raw).strip()
    try:
        parts = shlex.split(text)
    except ValueError as exc:
        raise WorkspaceValidationError(
            f"editor command could not be parsed ({exc}). Check the quoting."
        ) from exc
    if not parts:
        raise WorkspaceValidationError("editor command is empty.")

    head = parts[0]
    candidate = Path(head).expanduser()
    if candidate.is_absolute() or head.startswith("~") or os.sep in head:
        resolved = str(candidate) if candidate.exists() else None
    else:
        resolved = shutil.which(head)
    if resolved is None:
        raise WorkspaceValidationError(
            f"editor not found: {head}. Install it, or give an absolute path."
        )
    if not os.access(resolved, os.X_OK) or Path(resolved).is_dir():
        raise WorkspaceValidationError(f"editor is not executable: {resolved}.")

    return " ".join([shlex.quote(resolved)] + [shlex.quote(p) for p in parts[1:]])


def classify_env_name(name: str) -> str:
    upper = name.upper()
    if upper.startswith(RESERVED_ENV_PREFIXES):
        return "blocked"
    if upper in WARNED_ENV_NAMES:
        return "warned"
    if upper.startswith(WARNED_ENV_PREFIXES):
        return "warned"
    if any(hint in upper for hint in _CREDENTIAL_HINTS):
        return "warned"
    return "accepted"


def validate_env_map(raw: Optional[Dict[str, str]]) -> Tuple[Dict[str, str], List[str]]:
    if not raw:
        return {}, []
    if not isinstance(raw, dict):
        raise WorkspaceValidationError(
            "environment variables must be a set of name/value pairs."
        )

    env: Dict[str, str] = {}
    warnings: List[str] = []
    for name, value in raw.items():
        key = str(name).strip()
        if not key:
            raise WorkspaceValidationError(
                "an environment variable has an empty name."
            )
        if not ENV_NAME_RE.match(key):
            raise WorkspaceValidationError(
                f"{key!r} is not a valid environment variable name. Use "
                "letters, digits and underscore, starting with a letter or "
                "underscore."
            )

        tier = classify_env_name(key)
        if tier == "blocked":
            prefixes = " / ".join(RESERVED_ENV_PREFIXES)
            raise WorkspaceValidationError(
                f"{key} is reserved. Names beginning {prefixes} "
                "carry this app's own per-session hook channel; setting one "
                "here would misroute hook events silently rather than fail."
            )

        text = "" if value is None else str(value)
        if "\x00" in text:
            raise WorkspaceValidationError(
                f"the value for {key} contains a NUL byte, which no "
                "environment variable can hold."
            )
        if "\n" in text or "\r" in text:
            raise WorkspaceValidationError(
                f"the value for {key} contains a line break. Environment "
                "values are single-line."
            )

        if tier == "warned":
            warnings.append(
                f"{key} overrides an environment variable the shell or an "
                "agent may already rely on. It was saved; check it if a "
                "terminal behaves oddly."
            )
        env[key] = text

    return env, warnings


def machine_ipv4_addresses() -> List[str]:
    found: List[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if addr not in found:
                found.append(addr)
    except OSError:
        return []
    return found


def validate_bind_host(raw: Optional[str], known: Optional[List[str]] = None) -> str:
    if _blank(raw):
        return ""
    text = str(raw).strip()
    try:
        socket.inet_aton(text)
    except OSError as exc:
        raise WorkspaceValidationError(
            f"{text!r} is not an IPv4 address. A bind address must be an "
            "address, not a hostname."
        ) from exc
    if text.count(".") != 3:
        raise WorkspaceValidationError(
            f"{text!r} is not a full IPv4 address."
        )
    if text in UNIVERSAL_BIND_HOSTS:
        return text

    addresses = machine_ipv4_addresses() if known is None else known
    if not addresses:
        raise WorkspaceValidationError(
            f"this machine's addresses could not be enumerated, so whether "
            f"{text} can be bound cannot be determined. Choose 127.0.0.1 or "
            "0.0.0.0, which are always bindable."
        )
    if text not in addresses:
        raise WorkspaceValidationError(
            f"{text} is not an address this machine holds "
            f"({', '.join(addresses)}), so the server could not bind it."
        )
    return text


def build_spawn_env(
    workspace: Dict[str, object], app_env: Dict[str, str]
) -> Dict[str, str]:
    merged: Dict[str, str] = {}

    user_env = workspace.get("env") or {}
    if isinstance(user_env, dict):
        for name, value in user_env.items():
            merged[str(name)] = "" if value is None else str(value)

    root = workspace.get("development_root")
    if root and str(root).strip():
        merged[DEV_ROOT_ENV] = str(root).strip()

    shell = workspace.get("default_shell")
    if shell and str(shell).strip():
        merged[SHELL_ENV] = str(shell).strip()

    merged.update(app_env)
    return merged
