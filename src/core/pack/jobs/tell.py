
from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import structlog

from src.core.pack.jobs.types import JobRecord, JobState

log = structlog.get_logger(__name__)

STATE_WORDS = {"question": "asks a question", "done": "finished", "failed": "failed", "lost": "lost contact"}


STATE_TAILS = {"done": 'Its result is ready: job_wait("{id}") returns it at once.', "question": 'job_wait("{id}") returns the question at once.',
               "failed": 'No result came back: job_wait("{id}") says why.', "lost": 'No result is ready: job_wait("{id}") says what is known.'}


class TellRefused(Exception):
    pass


@dataclass
class Receiver:

    id: str
    key: str
    uuid: Optional[str] = None
    epoch: Optional[int] = None


def check_receiver(caller_session: Optional[str], receiver: Optional[Receiver]) -> Receiver:
    if not caller_session or receiver is None:
        raise TellRefused("the job has no caller session to tell")
    if caller_session not in {receiver.id, receiver.key, receiver.uuid}:
        raise TellRefused("the receiver is not this job's caller session")
    return receiver


def message_text(job: JobRecord, state: str) -> str:
    where = job.peer_label or "another computer"
    tail = STATE_TAILS.get(state, STATE_TAILS["done"]).format(id=job.id)
    return f'job {job.id} on {where} {STATE_WORDS.get(state, state)}. {tail}'


async def resolve_receiver(app: Any, session_id: str) -> Optional[Receiver]:
    from src.core.crosstalk import directory
    from src.core.mcp.protocol import BatchView

    from src.core.pack.jobs.agent_facts import info_for_caller

    info = await info_for_caller(app.state.session_manager, session_id)
    if info is None or info.session is None:
        return None
    cards = await directory.list_cards(BatchView(app.state.session_manager, app), include_remote=False)
    card = next((c for c in cards if c["id"] == info.session.id), None)
    if card is None:
        return None
    uuid = card.get("session_uuid")
    return Receiver(card["id"], str(uuid or card["id"]), uuid, info.session.tmux_created_epoch)


def queue_notice(receiver: Receiver, text: str) -> str:
    from src.core.crosstalk import store
    from src.core.db import transaction

    now = time.time()
    msg_id = "m-" + secrets.token_urlsafe(12)
    with closing(store._conn()) as conn, transaction(conn):
        conn.execute(
            """INSERT INTO crosstalk_messages
               (id,source,thread,sender_key,receiver_key,sender_id,receiver_id,receiver_uuid,receiver_epoch,
                sender_name,sender_provider,text,status,created_at,expires_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (msg_id, "system", "t-job-" + secrets.token_urlsafe(6), "crosstalk-system", receiver.key, "crosstalk-system", receiver.id,
             receiver.uuid, receiver.epoch, "carnivore:job", "system", text, "queued", now, now + store.MESSAGE_LIFETIME))
    store._notify()
    return msg_id


def claim(store: Any, job_id: str, token: str) -> bool:
    with store._tx() as conn:
        moved = conn.execute("UPDATE jobs SET notified_state=? WHERE id=? AND COALESCE(notified_state,'')<>?", (token, job_id, token)).rowcount
    return bool(moved)


def wake_dispatcher(app: Any, receiver_key: str) -> None:
    from src.core.crosstalk.delivery import dispatcher

    dispatcher.wake(app, receiver_key)


async def notify_caller(app: Any, store: Any, job: JobRecord, token: str, *,
                        resolve: Callable[[Any, str], Awaitable[Optional[Receiver]]] = resolve_receiver,
                        queue: Callable[[Receiver, str], str] = queue_notice,
                        wake: Callable[[Any, str], None] = wake_dispatcher) -> bool:
    state = token.split(":", 1)[0]
    if not job.caller_session or state not in STATE_WORDS or JobState.HERE.value == state:
        return False
    if not await asyncio.to_thread(claim, store, job.id, token):
        return False
    try:
        receiver = check_receiver(job.caller_session, await resolve(app, job.caller_session))
    except TellRefused as exc:
        log.info("pack_job_notice_refused", job_id=job.id, reason=str(exc))
        return False
    await asyncio.to_thread(queue, receiver, message_text(job, state))
    wake(app, receiver.key)
    return True
