
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, FrozenSet, Optional

import structlog

from src.core.app_alerts import constants as alert_const
from src.core.app_alerts import service as alert_service
from src.core.messaging import accept, message_store, notices, store
from src.core.messaging.client import HttpProviderClient, ProviderClient, ProviderError
from src.core.messaging.secrets import MessagingSecrets, ProviderSecrets, SecretError

log = structlog.get_logger(__name__)

GAP_ALERT_PREFIX = "messaging.gap."

ClientFactory = Callable[[Dict[str, Any], ProviderSecrets], ProviderClient]


def default_client_factory(row: Dict[str, Any], secrets: ProviderSecrets) -> ProviderClient:
    return HttpProviderClient(row["id"], secrets.base_url, secrets.token, allow_private=bool(row["allow_private"]),
                              allow_plain_http=bool(row["allow_plain_http"]))


@dataclass
class ProviderState:

    row: Dict[str, Any]
    secrets: ProviderSecrets
    owner_senders: FrozenSet[str]
    client: ProviderClient
    task: Optional[asyncio.Task] = None
    gap_episode: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return str(self.row["id"])

    @property
    def caps(self) -> Dict[str, Any]:
        return self.row.get("capabilities") or {}


class MessagingRuntime:

    def __init__(self, app: Any, *, secrets: Optional[MessagingSecrets] = None,
                 client_factory: ClientFactory = default_client_factory, start_streams: bool = True) -> None:
        from src.core.messaging.delivery import Drainer

        self.app = app
        self.secrets = secrets or MessagingSecrets()
        self.client_factory = client_factory
        self.start_streams = start_streams
        self.providers: Dict[str, ProviderState] = {}
        self.drainer = Drainer(app, self)
        self._tasks: set = set()

    async def start(self) -> None:
        await asyncio.to_thread(message_store.recover_uncertain)
        for row in await asyncio.to_thread(store.list_providers):
            await self.load(row["id"])
        for uuid in store.pending_uuids():
            self.wake(uuid)

    async def load(self, provider_id: str) -> Optional[ProviderState]:
        await self.unload(provider_id)
        row = await asyncio.to_thread(store.get_provider, provider_id)
        if row is None:
            return None
        try:
            secrets = await self.secrets.load(provider_id)
        except SecretError as exc:
            log.warning("messaging_provider_secrets_unread", provider_id=provider_id, error_type=type(exc).__name__)
            await asyncio.to_thread(store.update_provider, provider_id, stream_state="keychain_unavailable")
            return None
        if secrets is None:
            await asyncio.to_thread(store.update_provider, provider_id, stream_state="no_secrets")
            return None
        state = ProviderState(row, secrets, accept.normalize_handles(secrets.owner_senders),
                              self.client_factory(row, secrets))
        self.providers[provider_id] = state
        if self.start_streams and row["enabled"]:
            from src.core.messaging.stream import run_stream

            state.task = asyncio.create_task(run_stream(self, state))
            state.task.add_done_callback(self._task_done)
        return state

    async def unload(self, provider_id: str) -> None:
        state = self.providers.pop(provider_id, None)
        if state is not None and state.task is not None:
            state.task.cancel()
            try:
                await state.task
            except asyncio.CancelledError:
                pass

    async def close(self) -> None:
        for pid in list(self.providers):
            await self.unload(pid)
        self.drainer.close()
        for task in list(self._tasks):
            task.cancel()

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.warning("messaging_task_failed", error_type=type(task.exception()).__name__)

    def spawn(self, coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def wake(self, session_uuid: str) -> None:
        self.drainer.wake(session_uuid)

    def on_status(self, session_id: str, status: str) -> None:
        if not store.pending_uuids():
            return
        self.spawn(self._status_edge(session_id))

    async def _status_edge(self, session_id: str) -> None:
        info = await self.app.state.session_manager.get_session_info(session_id=session_id)
        uuid = store.uuid_for_row(info.session_row_id) if info is not None else None
        if uuid and store.has_pending(uuid):
            self.wake(uuid)

    async def send_notice(self, state: ProviderState, conversation_id: str, name: str, episode: Optional[str],
                          **params: object) -> bool:
        if not state.caps.get("send"):
            return False
        if episode is not None and not await asyncio.to_thread(message_store.claim_notice, conversation_id, name, episode):
            return False
        conversation = state.secrets.conversations.get(conversation_id)
        if not conversation:
            return False
        text = notices.notice_text(name, **params)
        row_id = await asyncio.to_thread(message_store.insert_outbound, {
            "provider_id": state.id, "conversation_id": conversation_id, "kind": "notice", "text": text})
        try:
            result = await state.client.send(conversation, text, reply_to=None, client_ref=row_id)
        except ProviderError as exc:
            await asyncio.to_thread(message_store.finish_outbound, row_id, status=exc.log_status,
                                    reason=exc.owner_text)
            log.warning("messaging_notice_failed", provider_id=state.id, notice=name, code=exc.code,
                        detail=exc.detail)
            return False
        await asyncio.to_thread(message_store.finish_outbound, row_id, status="delivered",
                                provider_message_id=result.message_id, sent_at=result.sent_at)
        if result.replayed:
            await asyncio.to_thread(message_store.record_replay_proof, state.id)
        log.info("messaging_notice_sent", provider_id=state.id, conversation_id=conversation_id, notice=name)
        return True

    async def on_gap(self, state: ProviderState, *, after: int, oldest: int) -> None:
        episode = f"{after}:{oldest}"
        now = time.time()
        last = state.row.get("last_event_at")
        await asyncio.to_thread(store.update_provider, state.id, gap={"after": after, "oldest": oldest, "at": now})
        if await asyncio.to_thread(message_store.claim_notice, "", "gap_alert:" + state.id, episode):
            alert_service.raise_alert(GAP_ALERT_PREFIX + state.id, source="messaging", severity=alert_const.SEV_WARN,
                                      title_key="app_alert.messaging.gap.title", params={"provider": state.row["name"]})
            log.warning("messaging_gap", provider_id=state.id, after=after, oldest=oldest)
        start = _clock(last) if last else notices.copy()["messaging.notice.gap_unknown_start"]
        bound = {b["conversation_id"] for b in await asyncio.to_thread(store.list_bindings)}
        for conv in await asyncio.to_thread(store.list_conversations, state.id):
            if conv["id"] in bound:
                await self.send_notice(state, conv["id"], notices.GAP, episode, start=start, end=_clock(now))


def _clock(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime("%a %m/%d %H:%M").lower()


async def install(app: Any) -> Optional[MessagingRuntime]:
    import sqlite3

    from src.core.db import DatastoreUnreadableError

    runtime = MessagingRuntime(app)
    try:
        await asyncio.to_thread(store.refresh_index)
        await runtime.start()
    except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        log.warning("messaging_install_failed", error_type=type(exc).__name__)
        app.state.messaging = None
        return None
    app.state.messaging = runtime
    log.info("messaging_installed", providers=len(runtime.providers))
    return runtime


async def uninstall(runtime: Optional[MessagingRuntime]) -> None:
    if runtime is not None:
        await runtime.close()
