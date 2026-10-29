
from __future__ import annotations

import fnmatch
import json
import tomllib
from typing import Any, Optional

from src.core.secret_scan import FILE_DETECTORS, scan_content

DENY_PATTERNS: tuple[str, ...] = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "id_ecdsa*", "auth.json",
    "credentials.json", ".credentials.json", ".netrc", ".npmrc", ".pypirc", "*.keychain*", "*.kdbx", "*.sqlite", "*.db",
    "*.env", ".git-credentials", "credentials", "credentials.*", ".pgpass", "*.ppk", "*.jks", "*.keystore", "service-account*.json",
    "service_account*.json", "client_secret*.json", "token.json", "tokens.json", ".htpasswd", ".s3cfg", ".boto", ".dockercfg",
    "*.p8", "*.gpg", "*.asc", "kubeconfig", "secrets.*",
)
SETTINGS_NAMES = frozenset({".mcp.json", "settings.json", "settings.local.json", "config.toml", ".claude.json"})
SENSITIVE_KEYS = frozenset({"env", "headers", "apiKeyHelper"})
SCAN_MAX_BYTES = 5 * 1024 * 1024


def name_problem(path: str) -> Optional[str]:
    base = path.rsplit("/", 1)[-1].lower()
    if any(fnmatch.fnmatchcase(base, pattern) for pattern in DENY_PATTERNS):
        return f"holds a credential file: {path}"
    return None


def _has_sensitive_key(node: Any) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SENSITIVE_KEYS and value not in (None, "", {}, []):
                return True
            if _has_sensitive_key(value):
                return True
    elif isinstance(node, list):
        return any(_has_sensitive_key(v) for v in node)
    return False


def settings_problem(path: str, data: bytes) -> Optional[str]:
    base = path.rsplit("/", 1)[-1].lower()
    if base not in SETTINGS_NAMES:
        return None
    try:
        text = data.decode("utf-8")
        parsed = tomllib.loads(text) if base.endswith(".toml") else json.loads(text)
    except (ValueError, UnicodeDecodeError):
        return None
    return f"holds settings with env or headers: {path}" if _has_sensitive_key(parsed) else None


def content_problem(path: str, data: bytes) -> Optional[str]:
    if len(data) > SCAN_MAX_BYTES:
        return None
    findings, _ = scan_content(path, data.decode("utf-8", errors="replace"), FILE_DETECTORS, excerpts=False, honour_pragma=False)
    if findings:
        return f"credential pattern in {path} line {findings[0].line}"
    return None


def file_problem(path: str, data: Optional[bytes]) -> Optional[str]:
    reason = name_problem(path)
    if reason is not None or data is None:
        return reason
    return settings_problem(path, data) or content_problem(path, data)
