
from __future__ import annotations

import asyncio
import json
import random
import socket
import sqlite3
import ssl
from typing import Any, AsyncIterator

import structlog
from websockets.exceptions import WebSocketException

from src.core.messaging import contract, events, store
from src.core.messaging.events import DETAIL_KEY
from src.core.messaging.client import LOCAL_NETWORK_DETAIL, ProviderError, local_network_hint
from src.core.notifications import http

log = structlog.get_logger(__name__)

BACKOFF_MIN_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 60.0

MAX_FRAME_BYTES = 64 * 1024

REST_IDLE_SECONDS = 15.0

OPEN_TIMEOUT_SECONDS = 10.0


async def _set_state(state: Any, value: str) -> None:
    if state.row.get("stream_state") != value:
        state.row = await asyncio.to_thread(store.update_provider, state.id, stream_state=value) or state.row


def _note_detail(state: Any, detail: Any) -> None:
    if state.extra.get(DETAIL_KEY) == detail:
        return
    state.extra[DETAIL_KEY] = detail
    if detail:
        log.warning("messaging_stream_detail", provider_id=state.id, detail=detail)


async def consume(rt: Any, state: Any, frames: AsyncIterator[str]) -> None:
    first = True
    async for raw in frames:
        try:
            data = json.loads(raw)
        except ValueError:
            raise contract.ContractError("frame is not json") from None
        if first:
            hello = contract.parse_hello(data)
            first = False
            await _set_state(state, "live")
            events.note_bridge_head(state, hello.latest)
            if hello.gap:
                await rt.on_gap(state, after=hello.after, oldest=hello.oldest)
            continue
        await events.handle_item(rt, state, contract.parse_event_or_skip(data))


def _ws_url(target: http.VettedTarget, cursor: int) -> str:
    scheme = "wss" if target.url.scheme == "https" else "ws"
    base = target.url.raw_path.decode("ascii").split("?")[0].rstrip("/")
    return f"{scheme}://{target.host}:{target.port}{base}/cpp/v1/events?after={int(cursor)}&routable=1"


def _open_socket(ip: str, port: int) -> socket.socket:
    sock = socket.create_connection((ip, port), timeout=OPEN_TIMEOUT_SECONDS)
    sock.setblocking(False)
    return sock


async def _ws_session(rt: Any, state: Any) -> None:
    from websockets.asyncio.client import connect

    target = await http.vet_target(state.secrets.base_url, policy=state.client.policy, timeout=OPEN_TIMEOUT_SECONDS)
    sock = await asyncio.to_thread(_open_socket, target.addrs[0], target.port)
    tls = ssl.create_default_context() if target.url.scheme == "https" else None
    async with connect(_ws_url(target, int(state.row.get("cursor") or 0)), sock=sock, ssl=tls,
                       server_hostname=target.host if tls else None, max_size=MAX_FRAME_BYTES,
                       open_timeout=OPEN_TIMEOUT_SECONDS, user_agent_header="carnivore-messaging",
                       proxy=None, compression=None,
                       additional_headers={"Authorization": f"Bearer {state.client.token}"}) as ws:
        async def frames() -> AsyncIterator[str]:
            async for frame in ws:
                yield frame if isinstance(frame, str) else frame.decode("utf-8")

        await consume(rt, state, frames())


async def _rest_session(rt: Any, state: Any) -> None:
    first = True
    while True:
        cursor = int(state.row.get("cursor") or 0)
        page = await state.client.events_page(cursor)
        events.note_bridge_head(state, page.latest)
        if first:
            await _set_state(state, "live")
            if page.gap:
                await rt.on_gap(state, after=cursor, oldest=page.oldest)
            first = False
        for item in page.events:
            await events.handle_item(rt, state, item)
        if int(state.row.get("cursor") or 0) <= cursor:
            await asyncio.sleep(REST_IDLE_SECONDS)


async def run_stream(rt: Any, state: Any) -> None:
    delay = BACKOFF_MIN_SECONDS
    while True:
        hint = None
        try:
            caps = await state.client.capabilities()
            state.row = await asyncio.to_thread(store.update_provider, state.id, capabilities=caps.as_json()) or state.row
            if not caps.receive:
                await _set_state(state, "send_only")
                return
            await _set_state(state, "connecting")
            await (_ws_session(rt, state) if caps.stream_ws else _rest_session(rt, state))
            delay = BACKOFF_MIN_SECONDS
            await _set_state(state, "reconnecting")
        except asyncio.CancelledError:
            raise
        except ProviderError as exc:
            log.warning("messaging_stream_provider_error", provider_id=state.id, code=exc.code, detail=exc.detail)
            hint = exc.detail if exc.detail == LOCAL_NETWORK_DETAIL else None
            await _set_state(state, exc.code)
        except http.GuardError as exc:
            hint = await local_network_hint(exc, state.secrets.base_url)
            log.warning("messaging_stream_blocked", provider_id=state.id, reason=exc.reason)
            await _set_state(state, "provider_blocked")
        except contract.ContractError as exc:
            log.warning("messaging_stream_contract_error", provider_id=state.id, reason=str(exc))
            await _set_state(state, "cpp_unsupported")
        except sqlite3.Error as exc:
            log.warning("messaging_stream_store_error", provider_id=state.id, error_type=type(exc).__name__)
            try:
                await _set_state(state, "store_error")
            except sqlite3.Error:
                pass
        except (WebSocketException, OSError, ValueError, RuntimeError) as exc:
            hint = await local_network_hint(exc, state.secrets.base_url)
            log.warning("messaging_stream_dropped", provider_id=state.id, error_type=type(exc).__name__)
            await _set_state(state, "reconnecting")
        _note_detail(state, hint)
        await asyncio.sleep(delay * (0.5 + random.random()))
        delay = min(BACKOFF_MAX_SECONDS, delay * 2)
