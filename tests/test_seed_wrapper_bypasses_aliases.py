
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.agent_wrappers import EXAMPLE_WRAPPERS
from src.core.config_migration_steps import build_seed_wrappers


def _seed(has_cld=False, has_cldor=False):
    try:
        return build_seed_wrappers(has_cld=has_cld, has_cldor=has_cldor)
    except TypeError:
        return build_seed_wrappers(has_cld)


def test_the_plain_claude_seed_bypasses_aliases():
    plain = [w for w in _seed() if w["id"] == "claude"]
    assert plain, "the seed no longer contains a plain claude wrapper"
    script = plain[0]["script"]
    assert script.startswith("command claude"), (
        f"seeded plain-claude script is {script!r}; without `command` a "
        "user's `alias claude=...` hijacks every session this launches"
    )


def test_the_seeded_script_still_skips_permissions():
    plain = [w for w in _seed() if w["id"] == "claude"][0]
    assert "--dangerously-skip-permissions" in plain["script"]


def test_function_wrappers_do_NOT_use_command():
    for w in _seed(has_cld=True, has_cldor=True):
        if w["id"] in ("cld", "cldor"):
            entry = (w.get("entry") or "")
            assert not entry.startswith("command "), (
                f"{w['id']} calls a shell FUNCTION; `command` cannot find it"
            )


def test_the_offered_examples_already_bypass_aliases():
    for raw in EXAMPLE_WRAPPERS:
        script = raw.get("script") or ""
        if "claude" in script and raw.get("family") in ("claude", "local"):
            for line in script.splitlines():
                stripped = line.strip()
                if stripped.startswith("claude ") or stripped == "claude":
                    raise AssertionError(
                        f"{raw['id']} invokes a bare `claude`: {stripped!r}"
                    )
