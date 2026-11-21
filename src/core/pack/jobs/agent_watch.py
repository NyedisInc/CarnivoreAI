
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.pack.jobs.agent_types import UsageTotals
from src.core.pack.jobs.types import HostJob, HostState

log = structlog.get_logger(__name__)

POLL_S = 2.0
STRAIGHT_READS = 2
PARK_S = 600.0
UNREADABLE_S = 300.0
USAGE_EVERY_S = 30.0
RESULT_MAX = 16384
TIME_CAP_CODE = 124
ASK_KINDS = ("question", "plan_approval", "input")
OWNER_KINDS = ("permission", "startup")
_TAIL_BYTES = 4 * 1024 * 1024
_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


@dataclass(frozen=True)
class Look:

    kind: str
    qkind: str = ""
    text: str = ""


@dataclass(frozen=True)
class Read:

    text: Optional[str]
    last_at: Optional[float]


@dataclass(frozen=True)
class Ending:

    code: int
    detail: Optional[str] = None
    question: Optional[str] = None
    qkind: Optional[str] = None


def _dialog_text(obs: Any, fallback: str) -> str:
    from src.core.mcp.tools import redact_text

    dialog = getattr(obs.evidence, "dialog", None)
    text = fallback
    if dialog is not None:
        options = "; ".join(dialog.options)
        text = f"{dialog.question}\n{options}".strip() if options else str(dialog.question)
    return redact_text(text)[:RESULT_MAX]


def is_resting(obs: Any) -> bool:
    from src.core.attention import evidence as ev

    return obs is not None and not obs.stale and obs.verdict.state == ev.STATE_DONE_IDLE


def classify(obs: Any) -> Look:
    from src.core.attention import evidence as ev
    from src.core.attention import resolve as waiting

    if obs is None:
        return Look("unreadable")
    verdict, evidence = obs.verdict, obs.evidence
    dialog = getattr(evidence, "dialog", None)
    screen = getattr(evidence, "startup_screen", None)
    if (dialog is not None and getattr(dialog, "startup_kind", None)) or screen is not None:
        text = getattr(screen, "text", "") if screen is not None else ""
        return Look("owner", "startup", _dialog_text(obs, text or "a startup screen is waiting on this computer"))
    if verdict.state == ev.STATE_NEEDS_USER:
        if verdict.reason == ev.REASON_PERMISSION:
            return Look("owner", "permission", _dialog_text(obs, "a permission prompt is waiting on this computer"))
        registry = getattr(evidence, "registry", None)
        if registry is not None and getattr(registry, "waiting_for", None) in (waiting.WAITING_SANDBOX_REQUEST, waiting.WAITING_WORKER_REQUEST):
            return Look("owner", "permission", _dialog_text(obs, "a request is waiting on this computer"))
        kind = verdict.reason if verdict.reason in ASK_KINDS else "input"
        return Look("ask", kind, _dialog_text(obs, verdict.detail or "the worker asks for input"))
    if verdict.state == ev.STATE_DONE_IDLE and verdict.reason == ev.REASON_TURN_ENDED:
        return Look("finished")
    if verdict.state == ev.STATE_BUSY:
        return Look("working")
    if verdict.reason == ev.REASON_PANE_DEAD:
        return Look("dead")
    return Look("unreadable")


def _text_of(record: Dict[str, Any]) -> tuple:
    if record.get("isSidechain"):
        return False, None
    if record.get("type") == "assistant":
        content = (record.get("message") or {}).get("content")
    elif record.get("type") == "response_item" and (record.get("payload") or {}).get("role") == "assistant":
        content = record["payload"].get("content")
    else:
        return False, None
    if isinstance(content, str):
        return True, content or None
    parts = [str(b.get("text")) for b in content or [] if isinstance(b, dict) and b.get("type") in ("text", "output_text") and b.get("text")]
    return True, "\n".join(parts) or None


def _epoch(stamp: Any) -> Optional[float]:
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


def parse_transcript(lines: List[str]) -> Read:
    text: Optional[str] = None
    last_at: Optional[float] = None
    for raw in lines:
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        is_assistant, found = _text_of(record)
        if not is_assistant:
            continue
        at = _epoch(record.get("timestamp"))
        if at is not None and (last_at is None or at > last_at):
            last_at = at
        if found is not None:
            text = found
    return Read(text, last_at)


def _tail_lines(path: Path) -> List[str]:
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - _TAIL_BYTES))
        data = handle.read()
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[1:] if size > _TAIL_BYTES and lines else lines


def transcript_path(family: str, conversation: Optional[str], working_dir: Optional[str], profile_root: Optional[str]) -> Optional[Path]:
    if not conversation:
        return None
    if family == "claude":
        from src.core.session_token_usage import claude_reader

        projects = Path(profile_root) / "projects" if profile_root else None
        found = claude_reader.locate_transcript(conversation, working_dir=working_dir, projects_dir=projects).path
        return Path(found) if found else None
    return _codex_rollout(profile_root, conversation)


def _codex_rollout(profile_root: Optional[str], conversation: str) -> Optional[Path]:
    from src.core.attention.codex_gather import DEFAULT_CODEX_HOME, rollout_path_in_sessions

    if not _CONVERSATION_ID.fullmatch(conversation):
        return None
    home = profile_root or DEFAULT_CODEX_HOME
    found = rollout_path_in_sessions(home, conversation)
    if not found:
        return None
    real, sessions = Path(found).resolve(), (Path(home).expanduser() / "sessions").resolve()
    return real if sessions in real.parents else None


def read_transcript(family: str, conversation: Optional[str], working_dir: Optional[str], profile_root: Optional[str]) -> Read:
    path = transcript_path(family, conversation, working_dir, profile_root)
    if path is None:
        return Read(None, None)
    try:
        return parse_transcript(_tail_lines(path))
    except OSError as exc:
        log.info("pack_jobs_agent_transcript_unreadable", error=type(exc).__name__)
        return Read(None, None)


def read_usage_totals(family: str, conversation: Optional[str], working_dir: Optional[str], profile_root: Optional[str]) -> Optional[UsageTotals]:
    from src.core.session_token_usage.reader import SessionSubject, read_session_token_usage

    rollout: Optional[str] = None
    if family == "codex":
        found = transcript_path(family, conversation, working_dir, profile_root)
        if found is None:
            return None
        rollout = str(found)
    got = read_session_token_usage(SessionSubject(family, conversation, working_dir),
                                   projects_dir=Path(profile_root) / "projects" if profile_root and family == "claude" else None,
                                   codex_home=profile_root if family == "codex" else None, rollout_path=rollout)
    if got.state != "ok":
        return None
    return UsageTotals(input_tokens=got.input_tokens or 0, output_tokens=got.output_tokens or 0,
                       cache_read_tokens=got.cache_read_input_tokens or 0, cache_write_tokens=got.cache_creation_input_tokens or 0,
                       cost_usd=got.cost_estimate_usd)


def clip_result(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    from src.core.mcp.tools import redact_text

    return redact_text(text)[:RESULT_MAX]


@dataclass
class _Streaks:

    kind: str = ""
    count: int = 0
    unreadable_since: Optional[float] = None
    usage_at: float = 0.0
    parked_text: Optional[str] = None


class AgentWatch:

    def __init__(self, *, store: Any, observe: Callable[[str], Any], read_result: Callable[[HostJob], Awaitable[Read]],
                 read_usage: Callable[[HostJob], Awaitable[Optional[UsageTotals]]], park: Callable[..., Awaitable[None]],
                 unpark: Callable[[HostJob], Awaitable[None]], finish: Callable[..., Awaitable[None]], floor: Callable[[str], float],
                 busy_replying: Callable[[str], bool], clock: Callable[[], float], sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 poll_s: float = POLL_S) -> None:
        self.store, self._observe, self._read_result, self._read_usage = store, observe, read_result, read_usage
        self._park, self._unpark, self._finish, self._floor, self._replying = park, unpark, finish, floor, busy_replying
        self._clock, self._sleep, self._poll_s = clock, sleep, poll_s

    async def _usage(self, row: HostJob, st: _Streaks, now: float) -> None:
        if now - st.usage_at < USAGE_EVERY_S:
            return
        st.usage_at = now
        totals = await self._read_usage(row)
        if totals is not None:
            self.store.host_set(row.job_id, usage_json=json.dumps(totals.model_dump()))

    async def _end(self, row: HostJob, ending: Ending, result: Optional[str]) -> bool:
        await self._finish(row, ending, result)
        now = self.store.host_get(row.job_id)
        return now is None or now.state not in (HostState.RUNNING, HostState.PARKED)

    async def _closing(self, row: HostJob, st: _Streaks) -> bool:
        got = await self._read_result(row)
        if got.last_at is None or got.last_at <= self._floor(row.job_id) or got.text is None:
            return False
        return await self._end(row, Ending(0), clip_result(got.text))

    async def run(self, job_id: str) -> None:
        st = _Streaks()
        while True:
            row = self.store.host_get(job_id)
            if row is None or row.state not in (HostState.RUNNING, HostState.PARKED) or row.body != "agent":
                return
            now = self._clock()
            if row.started_at and now - row.started_at >= row.time_cap_s:
                if await self._end(row, Ending(TIME_CAP_CODE, "time cap"), clip_result((await self._read_result(row)).text)):
                    return
            look = classify(self._observe(row.worker_session_id or ""))
            st.count = st.count + 1 if look.kind == st.kind else 1
            st.kind = look.kind
            if look.kind != "unreadable":
                st.unreadable_since = None
            if look.kind == "working":
                if row.state == HostState.PARKED and not self._replying(job_id):
                    await self._unpark(row)
                st.parked_text = None
            elif look.kind == "finished" and st.count >= STRAIGHT_READS and not self._replying(job_id):
                if await self._closing(row, st):
                    return
            elif look.kind in ("ask", "owner") and st.count >= STRAIGHT_READS and st.parked_text != look.text:
                await self._park(row, look.qkind, look.text)
                st.parked_text = look.text
            elif look.kind == "dead" and st.count >= STRAIGHT_READS:
                if await self._end(row, Ending(1, "worker exited"), clip_result((await self._read_result(row)).text)):
                    return
            elif look.kind == "unreadable":
                st.unreadable_since = now if st.unreadable_since is None else st.unreadable_since
                if now - st.unreadable_since >= UNREADABLE_S:
                    if await self._end(row, Ending(1, "worker status unreadable"), clip_result((await self._read_result(row)).text)):
                        return
            row = self.store.host_get(job_id) or row
            if row.state == HostState.PARKED and row.parked_at and now - row.parked_at >= PARK_S:
                ask = row.question_kind in ASK_KINDS
                if await self._end(row, Ending(0 if ask else 1, "question" if ask else f"the worker waited for this computer's owner ({row.question_kind})",
                                               row.question, row.question_kind), clip_result((await self._read_result(row)).text) if ask else None):
                    return
            try:
                await self._usage(row, st, now)
            except (OSError, ValueError) as exc:
                log.info("pack_jobs_agent_usage_unreadable", job_id=job_id, error=type(exc).__name__)
            await self._sleep(self._poll_s)
