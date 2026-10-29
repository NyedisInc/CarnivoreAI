
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from src.core.product_identity import is_owned_session_name
from src.core.session_respawn import PANE_ALIVE, PANE_DEAD, PANE_UNKNOWN

TMUX_GONE: str = "gone"

TMUX_PRESENT: str = "present"

TMUX_UNKNOWN: str = "unknown"

ALL_TMUX_PRESENCE: frozenset[str] = frozenset(
    {TMUX_GONE, TMUX_PRESENT, TMUX_UNKNOWN}
)


@dataclass(frozen=True)
class TmuxPresence:

    outcome: str
    detail: str = ""
    listed: int = 0

    @property
    def gone(self) -> bool:
        return self.outcome == TMUX_GONE


def tmux_presence(
    name: Optional[str],
    *,
    listing_ok: bool,
    listing_complete: bool,
    names: Optional[Sequence[str]],
    namespace_prefix: str = "cloude_",
) -> TmuxPresence:
    target = (name or "").strip()
    if not target:
        return TmuxPresence(
            outcome=TMUX_UNKNOWN,
            detail=(
                "no tmux session name was given, so whether it is still "
                "running was not evaluated"
            ),
        )
    if not listing_ok:
        return TmuxPresence(
            outcome=TMUX_UNKNOWN,
            detail=(
                "the tmux socket could not be listed, so whether this "
                "session is still running was not evaluated"
            ),
        )
    rows = [str(n).strip() for n in (names or [])]
    if target in rows:
        return TmuxPresence(
            outcome=TMUX_PRESENT,
            detail=(
                f"the tmux session {target!r} is still on the socket, so "
                "it restarts in place rather than being recreated"
            ),
            listed=len(rows),
        )
    if not listing_complete:
        return TmuxPresence(
            outcome=TMUX_UNKNOWN,
            detail=(
                "the tmux listing was incomplete, so this session's "
                "absence from it is not evidence that it is gone"
            ),
            listed=len(rows),
        )
    if namespace_prefix and not is_owned_session_name(target):
        return TmuxPresence(
            outcome=TMUX_UNKNOWN,
            detail=(
                f"the tmux session {target!r} is outside this app's "
                f"{namespace_prefix!r} namespace, which the listing does "
                "not cover, so its absence was not measured"
            ),
            listed=len(rows),
        )
    return TmuxPresence(
        outcome=TMUX_GONE,
        detail=(
            f"the tmux session {target!r} is not on the socket, so there "
            "is no pane to restart and this session can only come back "
            "as a new one"
        ),
        listed=len(rows),
    )


def pane_state_for(presence: TmuxPresence) -> str:
    if presence.outcome == TMUX_GONE:
        return PANE_DEAD
    if presence.outcome == TMUX_PRESENT:
        return PANE_ALIVE
    return PANE_UNKNOWN
