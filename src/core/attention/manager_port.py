from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, MutableMapping, Optional, Protocol


class _BackendRegistry(Protocol):

    backends: Mapping[str, Any]


class _HookTokens(Protocol):

    def name_for(self, session_id: str) -> Optional[str]:
        pass


class _UnreadStore(Protocol):

    def set_flag(self, tmux_name: Optional[str], field_name: str, value: bool, epoch: Optional[int] = None) -> None:
        pass


class _ToastInbox(Protocol):

    def ack(self, session_id: str, toast_id: str, reason: str) -> bool:
        pass


class _StartupGateLedger(Protocol):

    def record_hook(self, tmux_name: Optional[str], *, epoch: Optional[int] = None, now: Optional[datetime] = None) -> None:
        pass


class SideEffectsManager(Protocol):

    _registry: _BackendRegistry
    hook_tokens: _HookTokens
    _instance_epochs: MutableMapping[str, int]
    _unread_store: _UnreadStore
    _toast_inbox: _ToastInbox
    _startup_gate_ledger: _StartupGateLedger

    def _unread_epoch(self, tmux_name: Optional[str]) -> Optional[int]:
        pass

    def record_claude_lifecycle_event(
        self, session_id: str, event_kind: str, payload: dict, *, uuid_source: str = ..., tmux_name: Optional[str] = None,
    ) -> Any:
        pass

    def auto_ack_toasts(self, session_id: str, event_kind: str, cutoff: Optional[datetime] = None) -> list[str]:
        pass

    def _persist_work_stamp(
        self, session_id: str, tmux_name: Optional[str], kind: Optional[str], *,
        at: Optional[str] = None, throttle_key: Optional[str] = None,
    ) -> bool:
        pass

    def _persist_settled_activity_state(
        self, tmux_name: Optional[str], state: Optional[str], tmux_created_epoch: Optional[int],
    ) -> None:
        pass
