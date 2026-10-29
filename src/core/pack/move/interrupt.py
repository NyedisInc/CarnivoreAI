
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Sequence, Tuple
from urllib.parse import quote

import structlog

from src.core.pack.move import turn

logger = structlog.get_logger()
RUNNING = ("working", "working_subagent", "question")
CONTINUE_TEXT = "continue"
CONTINUE_WAIT_SECONDS = 90.0
CONTINUE_POLL_SECONDS = 3.0

Request = Callable[..., Awaitable[Tuple[int, Any]]]


def is_running(info: Any) -> bool:
    return info is not None and info.activity_status in RUNNING and not turn.shells_only(info)


def refusal_text(names: Sequence[str]) -> str:
    who = ", ".join(names)
    verb = "is" if len(names) == 1 else "are"
    return f"{who} {verb} running; the move will not start until {'it stops' if len(names) == 1 else 'they stop'} or you tick stop running agents now"


async def interrupt_running(find: Callable[[str], Awaitable[Any]], interrupt: Callable[[str], Awaitable[None]],
                            agents: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    done: List[Tuple[str, str]] = []
    for uuid, name in agents:
        if is_running(await find(uuid)):
            await interrupt(uuid)
            logger.info("pack_move_interrupted_agent", session_uuid=uuid, name=name)
            done.append((uuid, name))
    return done


def _reason(status: int, answer: Any) -> str:
    detail = answer.get("detail") if isinstance(answer, dict) else None
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("detail")
    return str(detail or f"the other computer answered {status}")[:200]


async def _tell_one(request: Request, uuid: str, name: str, wait: float, poll: float, text: str = CONTINUE_TEXT) -> Tuple[str, str]:
    loop = asyncio.get_running_loop()
    deadline, reason = loop.time() + wait, "it did not reach a ready prompt in time"
    while True:
        status, rows = await request("GET", "/sessions/list")
        found = next((r for r in rows if isinstance(r, dict) and r.get("session_uuid") == uuid), None) if status == 200 and isinstance(rows, list) else None
        session_id = (found.get("session") or {}).get("id") if found else None
        if session_id:
            status, answer = await request("POST", f"/sessions/{quote(str(session_id), safe='')}/skills/one-shot", json={"text": text, "idle_only": True})
            if status == 200:
                return name, ""
            reason = _reason(status, answer)
            if status not in (404, 409):
                return name, reason
        if loop.time() + poll > deadline:
            return name, reason
        await asyncio.sleep(poll)


async def tell_continue(request: Request, agents: Sequence[Tuple[str, str]], *, wait: float = CONTINUE_WAIT_SECONDS,
                        poll: float = CONTINUE_POLL_SECONDS, extra: str = "") -> Dict[str, Any]:
    async def one(uuid: str, name: str) -> Tuple[str, str]:
        try:
            return await _tell_one(request, uuid, name, wait, poll, f"{CONTINUE_TEXT}. {extra}" if extra else CONTINUE_TEXT)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack_move_continue_failed", name=name, error_type=type(exc).__name__)
            return name, str(getattr(exc, "detail", None) or "the link to the other computer dropped")[:200]

    results = await asyncio.gather(*(one(u, n) for u, n in agents))
    failed = [{"name": n, "reason": str(r)} for n, r in results if r]
    return {"told": len(results) - len(failed), "continue_failed": failed}
