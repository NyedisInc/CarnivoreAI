
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

import structlog

from src.core.product_identity import TMUX_SESSION_PREFIX, strip_session_prefix
from src.core.session_recreate_presence import TMUX_GONE, tmux_presence
from src.core.tmux_listing import TmuxListing, coerce_listing

logger = structlog.get_logger()

MAX_SUFFIX_ATTEMPTS: int = 999


@dataclass(frozen=True)
class NameClaim:

    name: str
    base: str
    reclaimed: bool
    presence: str


def probe_collision_listing(build_probe: Callable[[], Any]) -> TmuxListing:
    try:
        listing = coerce_listing(build_probe().discover_existing())
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("collision_probe_failed", error=str(exc))
        return TmuxListing.unavailable("probe_error", detail=str(exc))
    if not listing.ok:
        logger.warning(
            "collision_probe_unavailable",
            reason=listing.reason,
            note=(
                "name uniquification is falling back to owned + "
                "live-backend names only; tmux will still reject "
                "a genuine duplicate at create time"
            ),
        )
    return listing


def claim_tmux_name(
    base: str,
    *,
    listing: TmuxListing,
    active_names: Iterable[str],
    owned_names: Iterable[str],
    recreate: bool,
) -> NameClaim:
    live = set(listing.names) if listing.ok else set()
    presence = tmux_presence(
        base,
        listing_ok=listing.ok,
        listing_complete=listing.complete,
        names=listing.names if listing.ok else None,
    ).outcome
    stale = set(active_names) | set(owned_names)
    if recreate and presence == TMUX_GONE:
        return NameClaim(
            name=base, base=base, reclaimed=base in stale, presence=presence
        )
    taken = live | stale
    if base not in taken:
        return NameClaim(name=base, base=base, reclaimed=False, presence=presence)
    for suffix in range(2, MAX_SUFFIX_ATTEMPTS + 2):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return NameClaim(
                name=candidate, base=base, reclaimed=False, presence=presence
            )
    raise RuntimeError(
        f"Could not find a free tmux session name for "
        f"{base!r} after {MAX_SUFFIX_ATTEMPTS} attempts"
    )


TMUX_FORBIDDEN_CHARS = re.compile(r"[.:|\x00-\x08\x0e-\x1f\x7f]")
WHITESPACE_RUN = re.compile(r"\s+")


def sanitize_tmux_name(name: str) -> str:
    if not name:
        return ""
    replaced = TMUX_FORBIDDEN_CHARS.sub("_", name)
    collapsed = WHITESPACE_RUN.sub(" ", replaced)
    return collapsed.strip()


def base_name_for_project(project_name: Optional[str]) -> Optional[str]:
    if not project_name:
        return None
    stripped = project_name
    while True:
        remainder = strip_session_prefix(stripped)
        if remainder is None:
            break
        stripped = remainder
    sanitized = sanitize_tmux_name(stripped)
    return f"{TMUX_SESSION_PREFIX}{sanitized}" if sanitized else None
