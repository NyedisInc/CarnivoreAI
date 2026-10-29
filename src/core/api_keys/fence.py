
from __future__ import annotations

from typing import Optional

REASON = "api_key_forbidden"

FENCED: tuple[tuple[str, str], ...] = (
    ("/api/v1/api-keys", "api key management"),
    ("/api/v1/auth/", "sign in, refresh, sign out and authenticator setup"),
    ("/api/v1/mcp-admin/tokens", "mcp client tokens"),
    ("/api/v1/cplug-owner", "third-party plugin switch"),
    ("/api/v1/cplugs/safe-mode", "plugin safe mode"),
)


def _matches(path: str, prefix: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


def fenced_family(*paths: Optional[str]) -> Optional[str]:
    for path in paths:
        if not path:
            continue
        for prefix, family in FENCED:
            if _matches(path, prefix):
                return family
    return None
