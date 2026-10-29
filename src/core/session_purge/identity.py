
from __future__ import annotations

import sqlite3
from typing import Any, Iterable, List, Optional, Tuple

from src.core.db import table_exists
from src.core.inventory.identity import SAFE_CONVERSATION
from src.core.inventory.model import SessionIdentity

LOCAL_HOST_KEYS = (None, "", "local")



def live_blocker(ident: SessionIdentity, panes_ok: bool, panes: Iterable[Tuple[Any, Any, Any]],
                 live_row_ids: Iterable[str] = ()) -> Optional[str]:
    """Why the session counts as live, or None when it is measured asleep.

    Description: a pane with the row's tmux name counts as this session when its creation epoch matches, or when
      either epoch is unknown (ambiguous is refused, never guessed). A listing that did not answer refuses.
    Inputs: ident; panes_ok (bool); panes ((name, epoch, path) rows); live_row_ids (``ses_`` ids the server holds a
      live backend for whose row is this one, from the route). Output: str | None.
    Example: live_blocker(ident, True, [("carnivore_x", 17000, "/p")])
    """
    if not panes_ok:
        return "the tmux socket could not be listed, so the session cannot be proven asleep"
    if any(True for _ in live_row_ids):
        return "the server holds a live terminal for this session; stop it first"
    if not ident.tmux_name:
        return None
    for name, epoch, _path in panes:
        if name != ident.tmux_name:
            continue
        if epoch is None or ident.tmux_epoch is None or int(epoch) == ident.tmux_epoch:
            return f"its pane {ident.tmux_name} is live; stop the session first"
    return None


def static_blockers(conn: sqlite3.Connection, ident: SessionIdentity) -> List[str]:
    out: List[str] = []
    if ident.host_key not in LOCAL_HOST_KEYS:
        out.append(f"the session belongs to the paired computer {ident.host_key}; purge it there")
    children = [r[0] for r in conn.execute(
        "SELECT session_uuid FROM sessions WHERE parent_session_id = ? ORDER BY id", (ident.row_id,))]
    if children:
        out.append(f"{len(children)} other session(s) were forked or resumed from this one "
                   f"({', '.join(children[:5])}); purge or delete those first")
    if table_exists(conn, "swarm_agents"):
        agent = conn.execute("SELECT display_name FROM swarm_agents WHERE session_row_id = ?",
                             (ident.row_id,)).fetchone()
        if agent is not None:
            out.append(f"the session is the body of the Swarm agent {agent[0]}; retire the agent first")
    if ident.conversation and not SAFE_CONVERSATION.match(ident.conversation):
        out.append("the conversation id is not a plain id, so its files cannot be matched safely")
    return out
