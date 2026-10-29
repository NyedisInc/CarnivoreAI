
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Optional, Sequence

import structlog

from src.core.db_models import SESSION_LIFECYCLE_RUNNING
from src.core.product_identity import is_owned_session_name
from src.core.session_recreate_presence import (
    TMUX_GONE,
    TMUX_PRESENT,
    TMUX_UNKNOWN,
)

logger = structlog.get_logger()


REASON_INCUMBENT_IS_THE_LIVE_ROW: str = "incumbent_is_the_live_row"

REASON_INCUMBENT_RUNNING: str = "incumbent_lifecycle_running"

REASON_SUCCESSOR_INSTANCE: str = "successor_instance_holds_the_name"

REASON_NAME_ABSENT: str = "tmux_name_absent_from_socket"

REASON_PANES_DEAD: str = "retired_instance_panes_dead"

REASON_NAME_PRESENT: str = "tmux_name_present_on_socket"

REASON_UNMEASURED: str = "unmeasured"


def _all_panes_dead(rows: Sequence[str], name: str, epoch: Optional[int]) -> Optional[bool]:
    if isinstance(epoch, bool) or not isinstance(epoch, int) or not rows:
        return None
    states: list[str] = []
    for row in rows:
        parts = row.split("|", 2)
        if len(parts) != 3 or parts[2] != name or parts[0] != str(epoch) or parts[1] not in ("0", "1"):
            return None
        states.append(parts[1])
    return all(state == "1" for state in states)


def probe_dead_instance_panes(socket: str, name: str, epoch: Optional[int]) -> Optional[bool]:
    from src.core.tmux_backend import LIST_TIMEOUT_SECONDS, TmuxBackend
    from src.core.tmux_listing_parse import split_listing_rows

    if isinstance(epoch, bool) or not isinstance(epoch, int):
        return None
    try:
        backend = TmuxBackend.for_external(
            session_name=name, working_dir=Path.home(), on_output=None, socket_name=socket,
        )
        rc, out, _ = backend._run_tmux_sync(
            "list-panes", "-s", "-t", "=" + backend.tmux_session, "-F",
            "#{session_created}|#{pane_dead}|#{session_name}",
            check=False, timeout=LIST_TIMEOUT_SECONDS,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        logger.warning("conversation_takeover_pane_probe_failed", tmux_name=name,
                       error_type=type(exc).__name__)
        return None
    if rc != 0:
        return None
    return _all_panes_dead(split_listing_rows(out.decode("utf-8", errors="replace")), name, epoch)


@dataclass(frozen=True)
class TakeoverDecision:

    may_take: bool

    outcome: str

    reason: str

    detail: str = ""


def decide_conversation_takeover(
    *,
    incumbent_row_id: Optional[int],
    incumbent_lifecycle: Optional[str],
    incumbent_tmux_name: Optional[str],
    live_row_id: Optional[int],
    live_tmux_name: Optional[str],
    listing_ok: bool,
    listing_complete: bool,
    names: Optional[Sequence[str]],
    incumbent_panes_dead: Optional[bool] = None,
    namespace_prefix: str = "cloude_",
) -> TakeoverDecision:
    if incumbent_row_id is None or live_row_id is None:
        return TakeoverDecision(
            may_take=False,
            outcome=TMUX_UNKNOWN,
            reason=REASON_UNMEASURED,
            detail=(
                "one of the two rows was not identified, so whether they "
                "are the same row was not evaluated"
            ),
        )
    if int(incumbent_row_id) == int(live_row_id):
        return TakeoverDecision(
            may_take=False,
            outcome=TMUX_PRESENT,
            reason=REASON_INCUMBENT_IS_THE_LIVE_ROW,
            detail=(
                "the conversation is already recorded on the row being "
                "repaired, so there is nothing to take"
            ),
        )
    if (incumbent_lifecycle or "") == SESSION_LIFECYCLE_RUNNING:
        return TakeoverDecision(
            may_take=False,
            outcome=TMUX_UNKNOWN,
            reason=REASON_INCUMBENT_RUNNING,
            detail=(
                "the row holding this conversation is still recorded as "
                "running, so it is not retired and its conversation is "
                "not available"
            ),
        )

    incumbent_name = (incumbent_tmux_name or "").strip()
    live_name = (live_tmux_name or "").strip()
    if not incumbent_name:
        return TakeoverDecision(
            may_take=False,
            outcome=TMUX_UNKNOWN,
            reason=REASON_UNMEASURED,
            detail=(
                "the row holding this conversation names no tmux session, "
                "so whether that session is still running was not "
                "evaluated"
            ),
        )
    if not listing_ok:
        return TakeoverDecision(
            may_take=False,
            outcome=TMUX_UNKNOWN,
            reason=REASON_UNMEASURED,
            detail=(
                "the tmux socket could not be listed, so whether the "
                "holding row's session is still running was not evaluated"
            ),
        )
    if namespace_prefix and not is_owned_session_name(incumbent_name):
        return TakeoverDecision(
            may_take=False,
            outcome=TMUX_UNKNOWN,
            reason=REASON_UNMEASURED,
            detail=(
                "the tmux session %r is outside this app's %r namespace, "
                "which the listing does not cover, so its absence was not "
                "measured" % (incumbent_name, namespace_prefix)
            ),
        )

    rows = [str(name).strip() for name in (names or [])]
    if incumbent_name in rows:
        if incumbent_name == live_name:
            return TakeoverDecision(
                may_take=True,
                outcome=TMUX_GONE,
                reason=REASON_SUCCESSOR_INSTANCE,
                detail=(
                    "the tmux session %r on the socket is the instance "
                    "anchored to the row being repaired, and a name is "
                    "unique on a socket, so the holding row's own session "
                    "is gone" % incumbent_name
                ),
            )
        if listing_complete and incumbent_panes_dead is True:
            return TakeoverDecision(
                may_take=True,
                outcome=TMUX_GONE,
                reason=REASON_PANES_DEAD,
                detail="every pane of retired tmux instance %r was measured dead" % incumbent_name,
            )
        return TakeoverDecision(
            may_take=False,
            outcome=TMUX_PRESENT,
            reason=REASON_NAME_PRESENT,
            detail=(
                "the tmux session %r is still on the socket, so a live "
                "pane may be running this conversation" % incumbent_name
            ),
        )
    if not listing_complete:
        return TakeoverDecision(
            may_take=False,
            outcome=TMUX_UNKNOWN,
            reason=REASON_UNMEASURED,
            detail=(
                "the tmux listing was incomplete, so the holding row's "
                "absence from it is not evidence that its session is gone"
            ),
        )
    return TakeoverDecision(
        may_take=True,
        outcome=TMUX_GONE,
        reason=REASON_NAME_ABSENT,
        detail=(
            "the tmux session %r is not on the socket, so the row holding "
            "this conversation has no pane" % incumbent_name
        ),
    )
