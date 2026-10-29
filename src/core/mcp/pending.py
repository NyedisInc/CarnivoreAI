
from __future__ import annotations

import asyncio
import json
import secrets
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from src.core.approvals.bounds import SUMMARY_MAX, fit_text
from src.core.mcp.approvals import display, typed_confirm
from src.core.mcp.approvals.persist import ActionFile, ApprovalsStoreError
from src.core.mcp.caller import AgentCaller
from src.models.dialogs import ACTION_BODY_MAX_CHARS

logger = structlog.get_logger()

RESOLVED_KEEP_SECONDS = 24 * 60 * 60
MAX_DECIDED_KEPT = 200
MAX_WAIT_SECONDS = 50
MAX_PENDING_PER_CALLER = 5
MAX_PENDING_TOTAL = 100

MAX_SHOWN_PAYLOAD_CHARS = ACTION_BODY_MAX_CHARS

PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"
REFUSED = "refused"
EXPIRED = "expired"

Executor = Callable[[], Awaitable[dict]]
Recheck = Callable[["PendingAction"], Awaitable[str]]
Replay = Callable[["PendingAction"], Awaitable[dict]]


class PendingLimitError(ValueError):
    pass


class ActionRefused(RuntimeError):
    pass


def format_payload(args: dict) -> str:
    return "\n".join(f"{json.dumps(str(k))[1:-1]}: {json.dumps(v, default=str)}" for k, v in args.items())


def refused_result(reason: str) -> dict:
    return {"content": [{"type": "text", "text": f"refused: {reason}; nothing was done"}], "isError": True}


_PRIVATE = ("tool_args", "caller_env_id", "dedupe_key", "beast_eligible", "target_epoch", "target_name", "decided_at")


@dataclass
class PendingAction:
    """
    Fields: ``id``; ``created_at`` (epoch seconds); ``expires_at`` (always None: nothing expires);
    ``caller_session_id`` / ``caller_env_id`` / ``caller_tmux`` (the asking pane: registry id, env id, tmux name);
    ``target_session_id``, ``target_tmux``, ``target_name`` (label) and ``target_epoch`` (the tmux instance pinned
    at ask time, None when the target is not a local session); ``action`` (park name); ``tool`` / ``tool_args`` (the
    call that parked it, for a replay); ``args_summary``; ``plain`` (the row's sentence); ``status``; ``reason``
    (why refused); ``result``; ``execute`` (closure, None for an item restored from disk); ``args`` (shown).
    """

    id: str
    created_at: float
    caller_session_id: str
    caller_tmux: str
    target_session_id: str
    target_tmux: str
    action: str
    args_summary: str
    execute: Optional[Executor] = field(default=None, repr=False)
    args: dict = field(default_factory=dict)
    dedupe_key: str = ""
    external_client: str = ""
    approval_source: str = "owner"
    beast_eligible: bool = True
    status: str = PENDING
    result: Optional[dict] = None
    decided_at: Optional[float] = None
    expires_at: Optional[float] = None
    caller_env_id: str = ""
    target_epoch: Optional[int] = None
    target_name: str = ""
    tool: str = ""
    tool_args: dict = field(default_factory=dict)
    plain: str = ""
    reason: str = ""
    confirm_text: str = ""
    in_use: dict = field(default_factory=dict)

    def caller(self) -> AgentCaller:
        return AgentCaller(session_id=self.caller_env_id or self.caller_session_id, tmux_name=self.caller_tmux,
                           current_session_id=self.caller_session_id, token_name=self.external_client)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": "agent_action", "created_at": self.created_at, "expires_at": None,
            "caller_session_id": self.caller_session_id, "caller_tmux": self.caller_tmux,
            "target_session_id": self.target_session_id, "target_tmux": self.target_tmux,
            "action": self.action, "tool": self.tool, "args_summary": self.args_summary,
            "plain": self.plain or self.args_summary, "args": self.args, "body": format_payload(self.args),
            "external_client": self.external_client, "status": self.status, "reason": self.reason,
            "approval_source": self.approval_source,
            "decided_at": self.decided_at, "result": self.result if self.status != PENDING else None,
            "confirm_text": self.confirm_text or None, "in_use": self.in_use or None,
            "display": display.build(self.action, self.args, self.target_name or self.target_tmux, self.args_summary,
                                     self.plain, self.confirm_text, live=bool(self.target_tmux), in_use=self.in_use),
        }

    def stored(self) -> dict:
        return {**self.as_dict(), **{k: getattr(self, k) for k in _PRIVATE}, "result": self.result}


def _restore(row: Dict[str, Any]) -> PendingAction:
    known = set(PendingAction.__dataclass_fields__) - {"execute", "expires_at"}
    return PendingAction(**{k: row[k] for k in known if k in row})


class PendingActions:

    def __init__(self, clock: Callable[[], float] = time.time, file: Optional[ActionFile] = None) -> None:
        self._clock = clock
        self._items: dict[str, PendingAction] = {}
        self._subscribers: list[Callable[[], None]] = []
        self._file: Optional[ActionFile] = None
        self._recheck: Optional[Recheck] = None
        self._replay: Optional[Replay] = None
        self.version = 0
        if file is not None:
            self.attach(file)

    def attach(self, file: ActionFile) -> int:
        self._file = file
        try:
            rows = file.load()
        except ApprovalsStoreError as exc:
            logger.error("agent_actions_restore_failed", error=str(exc))
            return 0
        restored = 0
        for row in rows:
            try:
                item = _restore(row)
            except TypeError as exc:
                logger.warning("agent_action_row_skipped", id=row.get("id"), error=str(exc)[:200])
                continue
            if item.status == APPROVED and item.result is None:
                # server stopped
                item.result = {"content": [{"type": "text", "text": f"{item.action}: the server stopped while it ran; "
                                            "whether it finished is unknown"}], "isError": True}
            self._items.setdefault(item.id, item)
            restored += 1
        logger.info("agent_actions_restored", count=restored, pending=sum(1 for i in self._items.values() if i.status == PENDING))
        self._sweep()
        self._changed()
        return restored

    def set_runtime(self, recheck: Optional[Recheck], replay: Optional[Replay]) -> None:
        self._recheck, self._replay = recheck, replay

    def subscribe(self, callback: Callable[[], None]) -> None:
        self._subscribers.append(callback)

    def _save(self, item: PendingAction) -> None:
        if self._file is None:
            return
        try:
            self._file.save(item.stored())
        except ApprovalsStoreError as exc:
            logger.error("agent_action_save_failed", id=item.id, error=str(exc))

    def _changed(self) -> None:
        self.version += 1
        for callback in list(self._subscribers):
            try:
                callback()
            except Exception as exc:  # noqa: BLE001
                logger.warning("pending_actions_subscriber_failed", error=str(exc))

    def _sweep(self) -> None:
        now = self._clock()
        decided = sorted((i for i in self._items.values() if i.status != PENDING),
                         key=lambda i: i.decided_at or i.created_at, reverse=True)
        gone = [i.id for at, i in enumerate(decided)
                if at >= MAX_DECIDED_KEPT or now - (i.decided_at or i.created_at) > RESOLVED_KEEP_SECONDS]
        for action_id in gone:
            del self._items[action_id]
        if gone and self._file is not None:
            try:
                self._file.delete(gone)
            except ApprovalsStoreError as exc:
                logger.warning("agent_action_forget_failed", error=str(exc))

    def create(
        self, *, caller_session_id: str, caller_tmux: str, target_session_id: str,
        target_tmux: str, action: str, args_summary: str, execute: Executor,
        args: Optional[dict] = None, dedupe_key: str = "", external_client: str = "",
        beast_eligible: bool = True, extra: Optional[Dict[str, Any]] = None, supersede: bool = False,
    ) -> PendingAction:
        self._sweep()
        args = args or {}
        args_summary = fit_text(args_summary, SUMMARY_MAX)
        if len(format_payload(args)) > MAX_SHOWN_PAYLOAD_CHARS:
            raise PendingLimitError("the payload is too long to show the owner in full, so it cannot be sent for approval; send less")
        waiting = [i for i in self._items.values() if i.status == PENDING]
        for item in waiting:
            if supersede and (item.caller_tmux, item.target_session_id, item.action, item.dedupe_key) == (
                    caller_tmux, target_session_id, action, dedupe_key):
                self._refresh(item, args_summary, execute, args, extra or {})
                return item
            if (item.caller_tmux, item.target_session_id, item.action, item.args, item.dedupe_key) == (
                    caller_tmux, target_session_id, action, args, dedupe_key):
                if item.execute is None:
                    item.execute = execute
                return item
        if sum(1 for i in waiting if i.caller_tmux == caller_tmux) >= MAX_PENDING_PER_CALLER:
            raise PendingLimitError(f"you already have {MAX_PENDING_PER_CALLER} actions waiting on the owner")
        if len(waiting) >= MAX_PENDING_TOTAL:
            raise PendingLimitError("too many agent actions are waiting on the owner")
        item = PendingAction(
            id="act_" + secrets.token_urlsafe(9), created_at=self._clock(),
            caller_session_id=caller_session_id, caller_tmux=caller_tmux,
            target_session_id=target_session_id, target_tmux=target_tmux,
            action=action, args_summary=args_summary, execute=execute, args=args, dedupe_key=dedupe_key,
            external_client=external_client, beast_eligible=beast_eligible, **(extra or {}),
        )
        self._items[item.id] = item
        self._save(item)
        self._changed()
        return item

    def _refresh(self, item: PendingAction, args_summary: str, execute: Executor, args: dict, extra: Dict[str, Any]) -> None:
        item.args_summary, item.execute, item.args = args_summary, execute, args
        for name in ("tool", "tool_args", "plain"):
            if name in extra:
                setattr(item, name, extra[name])
        self._save(item)
        self._changed()

    def get(self, action_id: str) -> Optional[PendingAction]:
        self._sweep()
        return self._items.get(action_id)

    def list(self) -> list[dict]:
        self._sweep()
        rows = [i for i in self._items.values() if i.status == PENDING]
        return [i.as_dict() for i in sorted(rows, key=lambda i: i.created_at)]

    def count_pending(self) -> int:
        return len(self.list())

    def beast_candidates(self) -> list[PendingAction]:
        self._sweep()
        from src.core.mcp.beast_mode import pending_eligible

        return [item for item in self._items.values() if item.status == PENDING and pending_eligible(item)]

    def decided(self) -> list[dict]:
        self._sweep()
        rows = [item for item in self._items.values() if item.status != PENDING]
        return [item.as_dict() for item in sorted(rows, key=lambda item: item.created_at, reverse=True)]

    def record_beast(self, *, caller_session_id: str, caller_tmux: str, external_client: str,
                     target_session_id: str, target_tmux: str, action: str, args_summary: str,
                     args: dict, result: dict, approval_source: str = "approved by beast mode") -> None:
        now = self._clock()
        item = PendingAction(
            id="act_" + secrets.token_urlsafe(9), created_at=now,
            caller_session_id=caller_session_id, caller_tmux=caller_tmux,
            target_session_id=target_session_id, target_tmux=target_tmux,
            action=action, args_summary=args_summary, execute=None,
            args=args, external_client=external_client, approval_source=approval_source,
            status=APPROVED, result=result, decided_at=now,
        )
        self._items[item.id] = item
        self._save(item)
        self._changed()

    async def approve(self, action_id: str, typed: Optional[str] = None) -> PendingAction:
        item = self.get(action_id)
        if item is not None and item.status == PENDING:
            typed_confirm.check(item.confirm_text, typed)
        item = self._claim(action_id)
        return await self.execute_claimed(item, typed=typed if item.confirm_text else None)

    async def execute_claimed(self, item: PendingAction, typed: Optional[str] = None) -> PendingAction:
        self._save(item)
        self._changed()
        token = typed_confirm.TYPED.set(typed)
        try:
            reason = await self._recheck(item) if self._recheck is not None else ""
            if reason:
                raise ActionRefused(reason)
            if item.execute is not None:
                item.result = await item.execute()
            elif self._replay is not None:
                item.result = await self._replay(item)
            else:
                raise ActionRefused("it was asked before a restart and this server cannot run it again")
        except ActionRefused as exc:
            item.status, item.reason, item.result = REFUSED, str(exc), refused_result(str(exc))
            logger.info("agent_action_refused_at_approve", id=item.id, action=item.action, reason=item.reason)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent_action_execute_failed", action=item.action, error=str(exc))
            item.result = {"content": [{"type": "text", "text": f"{item.action} failed: {type(exc).__name__}"}],
                           "isError": True}
        finally:
            typed_confirm.TYPED.reset(token)
        return self._decided(item)

    def _decided(self, item: PendingAction) -> PendingAction:
        item.decided_at = self._clock()
        self._save(item)
        self._changed()
        return item

    def claim_for_beast(self, action_id: str) -> PendingAction:
        item = self._claim(action_id)
        item.approval_source = "approved by beast mode"
        self._changed()
        return item

    def deny(self, action_id: str) -> PendingAction:
        item = self._decided(self._claim(action_id, status=DENIED))
        hook = _DENY_HOOKS.get(item.action)
        if hook is not None:
            try:
                hook(item)
            except Exception as exc:  # noqa: BLE001
                logger.warning("agent_action_deny_hook_failed", id=item.id, action=item.action, error=str(exc)[:200])
        return item

    def deny_for_caller(self, caller_tmux: str) -> int:
        ids = [i.id for i in self._items.values() if i.status == PENDING and i.caller_tmux == caller_tmux]
        for action_id in ids:
            self.deny(action_id)
        return len(ids)

    def _claim(self, action_id: str, status: str = APPROVED) -> PendingAction:
        item = self.get(action_id)
        if item is None:
            raise KeyError(action_id)
        if item.status != PENDING:
            raise ValueError(f"already {item.status}")
        item.status = status
        return item


_DENY_HOOKS: Dict[str, Callable[[PendingAction], None]] = {}


def on_deny(action: str, hook: Callable[[PendingAction], None]) -> None:
    _DENY_HOOKS[action] = hook


_store = PendingActions()


def get_store() -> PendingActions:
    return _store


def finished(item: PendingAction) -> bool:
    return item.status != PENDING and not (item.status == APPROVED and item.result is None)


async def wait_for(item: PendingAction, timeout: float) -> str:
    deadline = time.monotonic() + max(0.0, timeout)
    while not finished(item) and time.monotonic() < deadline:
        await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    return item.status


def _host_of(session_id: str) -> str:
    parts = session_id.split(":", 2)
    return parts[1] if parts[0] == "remote" and len(parts) == 3 else "local"


class AgentActionProvider:

    def __init__(self, store: PendingActions, get_manager: Callable[[], Any]) -> None:
        self._store = store
        self._manager = get_manager

    def signature(self) -> frozenset:
        return frozenset(("agent_action", row["id"], row["id"]) for row in self._store.list())

    async def items(self) -> list[dict]:
        manager = self._manager()
        out: list[dict] = []
        for row in self._store.list():
            info = (await manager.get_session_info(row["target_session_id"])
                    if manager is not None and row["target_session_id"] else None)
            out.append({
                "id": row["id"], "source": "agent_action", "host": _host_of(row["target_session_id"]),
                "session_id": row["target_session_id"],
                "session_name": (info.label if info is not None else None) or row["target_tmux"],
                "tmux_session": row["target_tmux"],
                "project": info.project_name if info is not None else None,
                "kind": row["action"], "caller": row["caller_tmux"], "action": row["action"],
                "external_client": row["external_client"],
                "args": row["args"], "body": row["body"], "summary": row["args_summary"], "question": row["args_summary"],
                "created_at": datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat(),
                "confirm_text": row.get("confirm_text"),
                "display": row.get("display"),
            })
        return out
