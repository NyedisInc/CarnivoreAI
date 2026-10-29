
from __future__ import annotations

import re
from pathlib import Path

import src.core.tmux_listing as tmux_listing

ROOT = Path(__file__).resolve().parents[3]
MOVED = (
    "LISTING_ENV_OVERRIDES", "REASON_CONNECT_FAILED", "STDERR_CONNECT_FAILED", "STDERR_NO_SERVER",
    "STDERR_UNRECOGNISED", "classify_tmux_stderr", "listing_env", "looks_like_no_server",
    "_CONNECT_ERROR_MARKER", "_CONNECT_ERRNO_RE", "_NO_SERVER_CONNECT_ERRNOS", "_NO_SERVER_MARKERS",
)
IMPORT = re.compile(r"from src\.core\.tmux_listing import (\([^)]*\)|[^\n]*)")


def test_tmux_listing_does_not_expose_the_moved_names() -> None:
    assert [n for n in MOVED if hasattr(tmux_listing, n)] == []


def test_nothing_imports_a_moved_name_from_tmux_listing() -> None:
    offenders = []
    for folder in ("src", "tests", "scripts", "verify"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.name == Path(__file__).name:
                continue
            for match in IMPORT.finditer(path.read_text(errors="ignore")):
                if any(re.search(rf"\b{n}\b", match.group(1)) for n in MOVED):
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_transcript_import_plan_does_not_re_export_the_path_helpers() -> None:
    import src.core.transcript_import_plan as plan

    assert not hasattr(plan, "SCRATCH_PREFIXES") and not hasattr(plan, "TITLE_MAX")
