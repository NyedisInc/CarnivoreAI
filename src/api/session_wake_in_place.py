
from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi.concurrency import run_in_threadpool

from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT, TmuxPresence

logger = structlog.get_logger()

HUSK_DEAD = "dead"
HUSK_ALIVE = "alive"
HUSK_OTHER = "other_instance"
HUSK_UNKNOWN = "unknown"

_REFUSALS = {
    HUSK_ALIVE: "its pane is running again, so there is nothing to wake. nothing was touched",
    HUSK_OTHER: "another tmux session now carries this name, so this one was not woken. nothing was touched",
    HUSK_UNKNOWN: "the tmux pane could not be read, so whether it is dead was not evaluated. nothing was touched",
    "presence_unknown": "the tmux socket could not be listed, so whether its husk is there was not evaluated. "
                        "nothing was touched",
}


def classify_husk(raw: Optional[str], name: str, epoch: Optional[int]) -> str:
    parts = (raw or "").strip().split("|", 2)
    if len(parts) != 3 or parts[2] != name or parts[0] not in ("0", "1") or epoch is None:
        return HUSK_UNKNOWN
    try:
        created = int(parts[1])
    except ValueError:
        return HUSK_UNKNOWN
    if created != int(epoch):
        return HUSK_OTHER
    return HUSK_DEAD if parts[0] == "1" else HUSK_ALIVE


def _refused(row: dict, presence: str, why: str, conversation: str = "unknown") -> Any:
    from src.api.session_sleep_routes import WakeResponse

    logger.info("session_wake_in_place_refused", session_uuid=row.get("session_uuid"),
                tmux_name=row.get("tmux_name"), presence=presence, reason=why)
    return WakeResponse(
        status="refused", session_uuid=str(row.get("session_uuid")), session_name=row.get("tmux_name"),
        presence=presence, conversation=conversation, working_dir=row.get("working_dir"),
        detail=f"cannot wake: {_REFUSALS[why]}",
    )


async def wake_dead_pane(
    app_state: Any, row: dict, presence: TmuxPresence, *, agent_type: Optional[str],
    account_id: Optional[str] = None, account_pinned: bool = False,
) -> Optional[Any]:
    from src.api import recreate_routes as rr
    from src.api.session_attach_routes import respawn_or_http
    from src.api.session_sleep_routes import WakeResponse
    from src.core.restart_live_gate import probe_line

    if presence.outcome == TMUX_GONE:
        return None
    if presence.outcome != TMUX_PRESENT:
        return _refused(row, presence.outcome, "presence_unknown")
    name = rr._safe(str(row.get("tmux_name") or ""))
    socket = str(row.get("tmux_socket") or rr._socket_name())
    epoch = row.get("tmux_created_epoch")
    verdict = classify_husk(await run_in_threadpool(probe_line, name, socket), name,
                            int(epoch) if epoch is not None else None)
    if verdict != HUSK_DEAD:
        return _refused(row, presence.outcome, verdict)
    result = await respawn_or_http(
        app_state.session_manager, name, socket_name=socket, agent_type=agent_type or None,
        account_id=account_id, account_pinned=account_pinned,
    )
    ok = bool(result.get("ok"))
    logger.info("session_wake_in_place", session_uuid=row.get("session_uuid"), tmux_name=name, ok=ok,
                kind=result.get("kind"), conversation=result.get("conversation"),
                killed_live_pane=result.get("killed_live_pane"))
    return WakeResponse(
        status="started" if ok else "refused", session_uuid=str(row.get("session_uuid")), session_name=name,
        session_id=result.get("session_id") if ok else None, tmux_session=name if ok else None,
        presence=presence.outcome, conversation=str(result.get("conversation") or "unknown"),
        command=result.get("command"), working_dir=row.get("working_dir"), detail=str(result.get("detail") or ""),
    )
