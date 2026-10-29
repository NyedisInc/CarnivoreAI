
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Dict, Optional, Protocol

if TYPE_CHECKING:
    from src.core.sessions.hook_token_authority import HookTokenAuthority
    from src.core.sessions.owned_tmux_ledger import OwnedTmuxLedger
    from src.core.sessions.registry import SessionRegistry
    from src.core.unread_store import UnreadStore


class SessionHost(Protocol):

    _registry: "SessionRegistry"
    _owned: "OwnedTmuxLedger"
    _instance_epochs: Dict[str, int]
    _unread_store: "UnreadStore"
    hook_tokens: "HookTokenAuthority"

    def _save_session_metadata(self) -> None:
        pass

    def _writable_datastore_connection(self) -> Optional[sqlite3.Connection]:
        pass

    def tmux_socket_name(self) -> str:
        pass
