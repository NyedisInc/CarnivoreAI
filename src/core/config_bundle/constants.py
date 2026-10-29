
from __future__ import annotations

from typing import Tuple

BUNDLE_KIND = "carnivore-config-bundle"
"""The ``kind`` field of every bundle; a file without it is not one of ours."""

BUNDLE_SCHEMA_VERSION = 1
"""The shape of the bundle file itself. Distinct from ``config_version``,
which is the shape of the config.json sections inside it."""

MAX_BUNDLE_BYTES = 2 * 1024 * 1024
"""Upper bound on an import body. A real bundle is a few tens of kilobytes."""

MAX_DIFF_ENTRIES = 500
"""Longest change list a preview returns before it says it was truncated."""

MAX_PREVIEW_CHARS = 160
"""Longest before/after value string a preview line carries."""

MAX_PINS = 2000
"""Most pinned-theme entries one bundle may carry."""

EXPORTED_SECTIONS: Tuple[str, ...] = (
    "jwt_expiry_minutes",
    "access_token_ttl_seconds",
    "refresh_token_ttl_seconds",
    "refresh_grace_seconds",
    "template_path",
    "common_slash_commands",
    "session",
    "auth_rate_limits",
    "notifications",
    "agents",
    "launch_profiles",
    "uploads",
    "providers",
    "workspace",
    "ui",
    "catalog",
    "provider_accounts",
    "relay",
    "browser",
)
"""The config.json top-level keys a bundle may carry: an ALLOWLIST. A key
not named here (a new secret-bearing block, ``totp_secret``, ``jwt_secret``)
is never exported and never imported, without anyone having to remember to
exclude it."""

OMITTED_BY_DESIGN: Tuple[str, ...] = (
    "totp_secret and jwt_secret (credentials; they live in the environment)",
    "server_prefs (bind address and tls choice are specific to one machine)",
    "provider credentials (accounts are exported as pointers only)",
    "notification channel secrets (slack webhook, pushover keys, ntfy topic)",
    "theme_script_consent (a per-install trust decision)",
    "project theme defaults (.cc.theme files live in each project folder)",
    "sessions, transcripts and databases (not configuration)",
)
"""Listed in every export so the file says, in plain words, what it is not."""

REFUSED_PREFERENCE_FIELDS = frozenset({"theme_script_consent"})
"""Preference fields a bundle never carries, out or in. A script consent
recorded on another machine names a theme id and no digest, so importing
one would mint an unbounded standing grant of theme-script approval."""
