"""The adopt path refuses to mint a row for a pane MEASURED dead.

THE RULE, and its two limits:

  * Only a probe that RAN and read ``#{pane_dead}`` = ``1`` refuses. A
    probe that could not run is ``None`` - CANNOT DETERMINE - and the
    adoption proceeds exactly as before. Not having looked is not
    evidence the pane died.
  * Only a pane with NO row for its exact instance triple is refused. An
    existing row keeps its current behaviour (a dead pane drops off the
    live list and belongs in Recent), so this gate can never strand a
    session the app already knows. A husk that shares its tmux NAME with
    a row but carries a different epoch is a different instance and has
    no row of its own, so it is refused like any other new husk.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import structlog

logger = structlog.get_logger()

PERSIST_PANE_DEAD = "pane_dead"

PANE_DEAD_TRUE = "1"

PANE_DEAD_FALSE = "0"


def probe_session_pane_dead(name: str, *, socket: str) -> Optional[bool]:
    """Measure whether one tmux session's pane 0 has exited.

    Description: one ``display-message -p '#{pane_dead}'`` against the
      named socket. NEVER RAISES. True only when tmux answered rc=0 with
      ``1``; False only when it answered rc=0 with ``0``. An unsafe name,
      a missing session, a timeout, a failed exec or any other output all
      answer None - CANNOT DETERMINE, never "dead".
    Inputs: name (str) - the tmux session name. socket (str) - the tmux
      socket it lives on.
    Output: bool | None.
    Example: probe_session_pane_dead('cloude_a', socket='cloude') -> False
    """
    if not name:
        return None
    from src.core.tmux_backend import LIST_TIMEOUT_SECONDS, TmuxBackend

    try:
        backend = TmuxBackend.for_external(
            session_name=name,
            working_dir=Path.home(),
            on_output=None,
            socket_name=socket,
        )
    except ValueError:
        logger.warning("pane_dead_probe_unsafe_name", tmux_name=name)
        return None
    try:
        rc, out, _err = backend._run_tmux_sync(
            "display-message",
            "-t",
            backend.tmux_session,
            "-p",
            "#{pane_dead}",
            check=False,
            timeout=LIST_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning(
            "pane_dead_probe_failed",
            tmux_name=name,
            tmux_socket=socket,
            error=str(exc),
        )
        return None
    if rc != 0:
        return None
    value = out.decode("utf-8", errors="replace").strip()
    if value == PANE_DEAD_TRUE:
        return True
    if value == PANE_DEAD_FALSE:
        return False
    return None


def make_pane_dead_probe(socket: str) -> Callable[[str], Optional[bool]]:
    return lambda name: probe_session_pane_dead(name, socket=socket)


def should_refuse_dead_husk(
    *,
    stored_row: Optional[Mapping[str, Any]],
    pane_dead: Optional[bool],
) -> bool:
    return not stored_row and pane_dead is True


def check_dead_husk(
    *,
    name: str,
    socket: str,
    epoch: int,
    stored_row: Optional[Mapping[str, Any]],
    pane_dead_probe: Optional[Callable[[str], Optional[bool]]],
) -> bool:
    """Probe (only when it could matter) and apply the refusal rule.

    Description: skips the subprocess entirely when a row already exists,
      because the rule cannot refuse that case. Logs
      ``adopt_persist_refused_pane_dead`` when it refuses.
    Inputs: name (str), socket (str), epoch (int) - the instance.
      stored_row (Mapping | None) - the row for that triple, if any.
      pane_dead_probe (callable | None) - name -> bool | None; None means
      no probe was wired and nothing is refused.
    Output: bool - True when the caller must write nothing.
    Example: check_dead_husk(name='a', socket='cloude', epoch=1,
                             stored_row=None, pane_dead_probe=probe)
    """
    if stored_row or pane_dead_probe is None:
        return False
    pane_dead = pane_dead_probe(name)
    if not should_refuse_dead_husk(stored_row=stored_row, pane_dead=pane_dead):
        return False
    logger.warning(
        "adopt_persist_refused_pane_dead",
        tmux_name=name,
        tmux_socket=socket,
        tmux_created_epoch=epoch,
        note=(
            "the pane was MEASURED dead and no row exists for this "
            "instance, so no row is minted for a husk"
        ),
    )
    return True
