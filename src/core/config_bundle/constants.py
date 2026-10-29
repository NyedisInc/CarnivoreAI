
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

AGENT_COMMAND_FIELDS: Tuple[str, ...] = ("script", "entry", "args", "env")
"""The keys of an ``agents.wrappers[]`` row that run or shape a command: the
shell source, its entry function, its arguments and its environment. An
import that writes any of them, new or changed, needs the code consent
(Joe (ccsliinc), 2026-10-28, #2557; ``command_guard``). A launch profile's
command fields (``before_launch``, ``custom_command``, ``flags``, ``env``,
``secrets``) are ``launch_profiles.share.executable_parts`` and gated by
``launch_profiles.bundle_guard``."""

WORKSPACE_ENV_KEY = "env"
"""``workspace.env``: NAME=value pairs injected into every spawned pane, so a
changed ``PATH`` or ``ZDOTDIR`` decides what runs. A new or changed key is a
command write (Joe (ccsliinc), 2026-10-28, #2557, "yes, same consent")."""

WORKSPACE_SHELL_KEY = "default_shell"
"""``workspace.default_shell``: the program every new terminal runs. A new
non-empty value is a command write (same ruling)."""

WORKSPACE_EDITOR_KEY = "default_editor"
"""``workspace.default_editor``: the command line run to open a file. A new
non-empty value is a command write (#2557, an application of the same ruling)."""

BROWSER_EXECUTABLE_KEY = "executable"
"""``browser.executable``: the browser program remote browser sessions launch."""

ACCOUNT_DIR_FIELDS: Tuple[str, ...] = ("claude_config_dir", "codex_home")
"""``provider_accounts.accounts[]`` folders handed to a spawned agent as
``CLAUDE_CONFIG_DIR`` / ``CODEX_HOME``: they pick the settings, hooks and
credentials the agent runs with, so a new or changed one is a command write."""
