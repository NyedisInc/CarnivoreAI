
from __future__ import annotations

from typing import Optional

RESERVED_SKILL_NAMES = frozenset(
    {
        "imagegen",
        "openai-docs",
        "plugin-creator",
        "review-agent",
        "skill-creator",
        "skill-installer",
        "init",
        "simplify",
        "code-review",
        "security-review",
        "loop",
        "schedule",
        "keybindings-help",
        "update-config",
        "claude-api",
        "design",
        "dataviz",
        "artifact-design",
        "artifact-diagramming",
        "artifact-capabilities",
        "workflow-authoring",
        "claude-in-chrome",
        "run",
        "fewer-permission-prompts",
    }
)

BUNDLED_THEME_NAMES = frozenset(
    {
        "acid_trip",
        "alien",
        "black_ops",
        "blade_runner",
        "carnivore",
        "carnivore-light",
        "claude",
        "dracula",
        "hermes",
        "lovecraft",
        "matrix",
        "metal",
    }
)

FIRST_PARTY_THEME_NAMES = frozenset(
    {
        "calming",
        "claw",
        "codex",
        "corporate_v2",
        "gameboy",
        "green_crt",
        "ice_forge",
        "jagermeister",
        "legacy_apple",
        "legacy_windows",
        "neon_city",
        "neural",
        "pokemon",
        "riot",
        "snes",
        "terminal",
    }
)

RETIRED_THEME_NAMES = frozenset(
    {
        "ascii-abyss",
        "ascii-astral",
        "ascii-bloom",
        "ascii-creator",
        "ascii-forge",
        "ascii-gold-master",
        "ascii-mantis",
        "ascii-oracle",
        "ascii-raven",
        "ascii-relic",
        "ascii-ronin",
    }
)
FIRST_PARTY_THEME_PUBLISHER = "carnivore"
LEGACY_FIRST_PARTY_PUBLISHER = "nyedis"
FIRST_PARTY_HANDLES = (FIRST_PARTY_THEME_PUBLISHER, LEGACY_FIRST_PARTY_PUBLISHER)


RESERVED_PUBLISHER_HANDLES = frozenset({"bundled", "nyedis", "carnivore", "external", "local"})

RESERVED_CLAIM_HANDLES = RESERVED_PUBLISHER_HANDLES | frozenset(
    {
        "acme", "admin", "administrator", "anthropic", "api", "catalog", "claude", "codex",
        "curator", "me", "moderator", "official", "openai", "root", "security", "skills", "staff",
        "support", "system", "users",
    }
)


def is_first_party_publisher(handle: Optional[str]) -> bool:
    return isinstance(handle, str) and handle.strip().lower() in FIRST_PARTY_HANDLES
RESERVED_THEME_NAMES = BUNDLED_THEME_NAMES | FIRST_PARTY_THEME_NAMES | RETIRED_THEME_NAMES

RESERVED_NAMES_FOR = {
    "skill": RESERVED_SKILL_NAMES,
    "theme": RESERVED_THEME_NAMES,
}


def is_reserved_name(
    name: str, kind: str = "skill", publisher: Optional[str] = None
) -> bool:
    key = name.strip().lower()
    if (
        kind == "theme"
        and key in FIRST_PARTY_THEME_NAMES
        and is_first_party_publisher(publisher)
    ):
        return False
    return key in RESERVED_NAMES_FOR.get(kind, frozenset())
