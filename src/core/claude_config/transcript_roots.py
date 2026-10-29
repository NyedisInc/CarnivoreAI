
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from src.core import claude_transcript_correlate
from src.core.claude_config import profile_roots
from src.core.claude_config.profile_roots import (  # noqa: F401
    PROJECTS_DIRNAME,
    ROOTS_TTL_SECONDS,
)


def claude_transcript_roots(config_path: Optional[Path] = None) -> Tuple[Path, ...]:
    return profile_roots.profile_subdir_roots(
        claude_transcript_correlate.default_projects_dir(), PROJECTS_DIRNAME, config_path
    )


def reset_transcript_roots_cache_for_tests() -> None:
    profile_roots.reset_profile_roots_cache_for_tests()
