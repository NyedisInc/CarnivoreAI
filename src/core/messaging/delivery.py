
from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from contextlib import closing
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.core.messaging import batch, message_store, notices, store
from src.core.session_delivery import bring_up

log = structlog.get_logger(__name__)

HOLD_CODES = frozenset({"pane_dialog_open", "dialog_unreadable", "pane_not_an_agent", "session_gone"})

_WAITED = {"dialog_open": batch.WAIT_DIALOG, "dialog_unreadable": batch.WAIT_DIALOG, "pane_dialog_open": batch.WAIT_DIALOG,
           "waking": batch.WAIT_ASLEEP, "asleep_wake_refused": batch.WAIT_ASLEEP,
           "session_not_running": batch.WAIT_NOT_RUNNING, "session_gone": batch.WAIT_NOT_RUNNING,
           "pane_not_an_agent": batch.WAIT_NOT_RUNNING}

_META_SAFE = re.compile(r"[^A-Za-z0-9_]")


async def session_cards(app: Any) -> Dict[str, dict]:
    from src.core.crosstalk import directory
    from src.core.mcp.protocol import BatchView

    cards = await directory.list_cards(BatchView(app.state.session_manager, app), include_remote=False,
                                       include_asleep=True)
    return {str(c["session_uuid"]): c for c in cards if c.get("session_uuid")}


def _row_exists(session_uuid: str) -> Optional[bool]:
    """Whether a ``sessions`` row carries this uuid; None when the store could not be read (never guessed)."""
    from src.core.db import DatastoreUnreadableError

    try:
        with closing(store._conn()) as conn:
            return conn.execute("SELECT 1 FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone() is not None
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        log.warning("messaging_session_row_unread", error_type=type(exc).__name__)
        return None


class Drainer:

    def __init__(self, app: Any, runtime: Any) -> None:
        self.app = app
        self.runtime = runtime
        self._tasks: Dict[str, asyncio.Task] = {}
        self._again: set = set()

    def wake(self, session_uuid: str) -> None:
        current = self._tasks.get(session_uuid)
        if current is not None and not current.done():
            self._again.add(session_uuid)
            return
        task = asyncio.create_task(self._run(session_uuid))
        self._tasks[session_uuid] = task
        task.add_done_callback(self._done)

    def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()

    @staticmethod
    def _done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            log.warning("messaging_drain_failed", error_type=type(task.exception()).__name__)

    async def _run(self, session_uuid: str) -> None:
        while True:
            self._again.discard(session_uuid)
            await self.drain(session_uuid)
            if session_uuid not in self._again:
                return

    async def _hold(self, rows: List[dict], reason: str, *, notice: Optional[str], name: str) -> None:
        await asyncio.to_thread(message_store.set_status, [r["id"] for r in rows], "held", reason=reason,
                                only_from=store.PENDING)
        if notice is None:
            return
        for binding_id in sorted({r["binding_id"] for r in rows}):
            binding = await asyncio.to_thread(store.get_binding, binding_id)
            state = self._provider_for(rows, binding_id)
            if binding is None or state is None or not binding["held_notice"]:
                continue
            first = min(r["id"] for r in rows if r["binding_id"] == binding_id)
            await self.runtime.send_notice(state, binding["conversation_id"], notice, f"{binding_id}:{first}",
                                           session=name)

    def _provider_for(self, rows: List[dict], binding_id: str) -> Any:
        pid = next((r["provider_id"] for r in rows if r["binding_id"] == binding_id), None)
        return self.runtime.providers.get(pid) if pid else None

    async def drain(self, session_uuid: str) -> None:
        rows = await asyncio.to_thread(message_store.pending_for, session_uuid)
        if not rows:
            return
        card = (await session_cards(self.app)).get(session_uuid)
        if card is None:
            exists = await asyncio.to_thread(_row_exists, session_uuid)
            if exists is False:
                for binding in await asyncio.to_thread(store.list_bindings, session_uuid=session_uuid):
                    await asyncio.to_thread(store.delete_binding, binding["id"], reason="session_deleted")
                return
            await self._hold(rows, "session_not_running", notice=notices.NOT_RUNNING, name=session_uuid[:8])
            return
        name = str(card.get("name") or session_uuid[:8])
        if card.get("asleep"):
            await self._wake_asleep(rows, session_uuid, name)
            return
        if card.get("status") == "dead":
            await self._hold(rows, "session_not_running", notice=notices.NOT_RUNNING, name=name)
            return
        from src.core.approvals.dialog_gate import CLEAR, OPEN, dialog_verdict

        verdict = await dialog_verdict(self.app, str(card["id"]))
        if verdict != CLEAR:
            reason = "dialog_open" if verdict == OPEN else "dialog_unreadable"
            log.info("messaging_held", session_uuid=session_uuid, reason=reason, rows=len(rows))
            await self._hold(rows, reason, notice=notices.HELD, name=name)
            return
        for binding_id in sorted({r["binding_id"] for r in rows}):
            await self._deliver_binding(str(card["id"]), name, [r for r in rows if r["binding_id"] == binding_id])

    async def _wake_asleep(self, rows: List[dict], session_uuid: str, name: str) -> None:
        from src.api.session_sleep_routes import wake_by_uuid  # noqa: PLC0415

        await self._hold(rows, "waking", notice=None, name=name)
        try:
            result = await wake_by_uuid(self.app.state, session_uuid)
            refused = result.status != "started"
            code = str(getattr(result, "code", "") or result.status)
        except HTTPException as exc:
            refused, code = True, f"http_{exc.status_code}"
        except (OSError, RuntimeError, LookupError, ValueError) as exc:
            refused, code = True, type(exc).__name__
        if refused:
            log.warning("messaging_wake_refused", session_uuid=session_uuid, reason=code, rows=len(rows))
            await self._hold(rows, "asleep_wake_refused", notice=notices.WAKE_REFUSED, name=name)
            return
        log.info("messaging_woke_session", session_uuid=session_uuid, rows=len(rows))
        try:
            await self._await_ready(session_uuid)
        except bring_up.BringUpFailed as exc:
            log.warning("messaging_woke_not_ready", session_uuid=session_uuid, rows=len(rows), error=str(exc))
            return
        await self.drain(session_uuid)

    async def _await_ready(self, session_uuid: str) -> str:
        ops = bring_up.ops_for_app(self.app.state)
        return await bring_up.wait_ready(ops, lambda info, keys: keys.get(info.session.id) == session_uuid,
                                         "the woken session")

    async def _deliver_binding(self, session_id: str, name: str, rows: List[dict]) -> None:
        binding_id = rows[0]["binding_id"]
        binding = await asyncio.to_thread(store.get_binding, binding_id)
        state = self._provider_for(rows, binding_id)
        if binding is None or state is None:
            return
        waited = {r["id"]: _WAITED.get(r["status"] == "held" and r["reason"] or "") for r in rows}
        batch_id = store.new_id("t_", 16)
        claimed = await asyncio.to_thread(message_store.set_status, [r["id"] for r in rows], "delivering",
                                          batch_id=batch_id, only_from=store.PENDING)
        if not claimed:
            return
        fresh = [await asyncio.to_thread(message_store.get_message, rid) for rid in claimed]
        pending = [batch.Pending(r["id"], r["text"], r["sent_at"], r["received_at"], waited.get(r["id"]))
                   for r in fresh if r is not None]
        from src.core.session_one_shot_gate import MAX_BODY_BYTES

        parts = batch.render(pending, now=time.time(), tz=None, copy=notices.copy(), owner=state.row["owner_label"],
                             provider=state.row["name"], can_reply=binding["direction"] in store.OUTBOUND,
                             max_bytes=MAX_BODY_BYTES - 1024)
        meta = {"source_kind": "messaging", "provider": _META_SAFE.sub("_", state.row["name"])[:40] or "provider"}
        for index, part in enumerate(parts):
            left = [rid for p in parts[index:] for rid in p.row_ids]
            outcome = await self._deliver_part(session_id, part.text, meta)
            if outcome is None:
                await asyncio.to_thread(message_store.set_status, list(part.row_ids), "delivered")
                continue
            status, reason = outcome
            await asyncio.to_thread(message_store.set_status, left, status, reason=reason)
            if status == "held" and reason in ("pane_dialog_open", "dialog_unreadable"):
                await self._hold([r for r in fresh if r and r["id"] in left], reason, notice=notices.HELD, name=name)
            return
        log.info("messaging_delivered", session_id=session_id, binding_id=binding_id, rows=len(claimed),
                 parts=len(parts), batch_id=batch_id)

    async def _deliver_part(self, session_id: str, text: str, meta: Dict[str, str]) -> Optional[tuple]:
        from src.api.channel_delivery import deliver_through_gates

        try:
            await deliver_through_gates(SimpleNamespace(app=self.app), session_id, text, meta, fresh_dialog_check=True)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            code = str(detail.get("code") or "paste_refused")
            if code in HOLD_CODES:
                return "held", code
            return "failed", "delivery_uncertain" if code == "paste_not_settled" else code
        except (OSError, RuntimeError, ValueError) as exc:
            log.warning("messaging_delivery_failed", session_id=session_id, error_type=type(exc).__name__)
            return "failed", "delivery_uncertain"
        return None
