
from __future__ import annotations

from typing import Optional

REASON = "api_key_forbidden"

FENCED: tuple[tuple[str, str], ...] = (
    ("/api/v1/api-keys", "api key management"),
    ("/api/v1/auth/", "sign in, refresh, sign out and authenticator setup"),
    ("/api/v1/mcp-admin/tokens", "mcp client tokens"),
    ("/api/v1/cplug-owner", "third-party plugin switch"),
    ("/api/v1/cplugs/safe-mode", "plugin safe mode"),
    ("/api/v1/cplugs/reviewboard/public", "public review links and their visitors"),
    ("/api/v1/catalog/computer-account", "the computer's carnivore account"),
    ("/api/v1/catalog/auth/signout-all", "signing every client out of carnivore"),
    ("/api/v1/catalog/account/sessions/revoke-others", "revoking the carnivore account's other sessions"),
    ("/api/v1/catalog/account/delete", "deleting the carnivore account"),
    ("/api/v1/pack/interim/confirm", "the owner's interim main confirm"),
    ("/api/v1/cplugs/save/mass-gone/clear", "lifting the backup vault's mass-gone freeze"),
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
