
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from src.core.claude_title_sync import read_newest_custom_title

TRANSCRIPT_READ = "read"

# no working directory
TRANSCRIPT_NO_CONVERSATION = "no_conversation"

TRANSCRIPT_UNREADABLE = "unreadable"

MAX_LINES_SCANNED = 200

TAIL_BYTES = 65536

BOOKKEEPING_TYPES = frozenset(
    {"file-history-snapshot", "summary", "bridge-session"}
)

SCHEDULED_TASK = re.compile(r'\A<scheduled-task\s+name="([^"]+)"')

SYNTHETIC_ENVELOPE = re.compile(r"<([a-zA-Z][\w-]*)\b[^>]*>.*?</\1>", re.DOTALL)

SYNTHETIC_BARE_TAG = re.compile(r"\A<[a-zA-Z][\w-]*\b[^>]*>\Z", re.DOTALL)


@dataclass(frozen=True)
class TranscriptFacts:

    path: str
    uuid: str
    status: str
    session_id: Optional[str] = None
    cwd: Optional[str] = None
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None
    custom_title: Optional[str] = None
    first_user_text: Optional[str] = None
    detail: Optional[str] = None

    @property
    def is_conversation(self) -> bool:
        return self.status == TRANSCRIPT_READ


def _user_text(record: dict) -> Optional[str]:
    if record.get("type") != "user" or record.get("isSidechain"):
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(part for part in parts if part).strip()
    else:
        return None
    if not text:
        return None

    scheduled = SCHEDULED_TASK.match(text)
    if scheduled:
        return f"scheduled task: {scheduled.group(1)}"

    stripped = SYNTHETIC_ENVELOPE.sub("", text).strip()
    if not stripped or SYNTHETIC_BARE_TAG.match(stripped):
        return None
    return stripped


def _read_head(path: str) -> tuple:
    cwd = session_id = first_ts = first_user = None
    saw_any = False
    with open(path, "rb") as handle:
        for index, raw in enumerate(handle):
            if index >= MAX_LINES_SCANNED:
                break
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            saw_any = True
            if cwd is None and isinstance(record.get("cwd"), str) and record["cwd"]:
                cwd = record["cwd"]
            if session_id is None and isinstance(record.get("sessionId"), str):
                session_id = record["sessionId"] or None
            if first_ts is None and isinstance(record.get("timestamp"), str):
                first_ts = record["timestamp"] or None
            if first_user is None:
                first_user = _user_text(record)
            if cwd and session_id and first_ts and first_user:
                break
    return cwd, session_id, first_ts, first_user, saw_any


def _read_last_timestamp(path: str, size: int) -> Optional[str]:
    start = max(0, size - TAIL_BYTES)
    with open(path, "rb") as handle:
        if start:
            handle.seek(start)
        window = handle.read()
    lines = window.split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]
    newest = None
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(record, dict) and isinstance(record.get("timestamp"), str):
            if record["timestamp"]:
                newest = record["timestamp"]
    return newest


def read_transcript_facts(path: str) -> TranscriptFacts:
    uuid = os.path.splitext(os.path.basename(path))[0]
    try:
        size = os.path.getsize(path)
        cwd, session_id, first_ts, first_user, saw_any = _read_head(path)
        last_ts = _read_last_timestamp(path, size)
    except OSError as exc:
        return TranscriptFacts(
            path=path,
            uuid=uuid,
            status=TRANSCRIPT_UNREADABLE,
            detail=f"the transcript could not be read: {exc.strerror or exc}",
        )

    if not cwd:
        return TranscriptFacts(
            path=path,
            uuid=uuid,
            status=TRANSCRIPT_NO_CONVERSATION,
            session_id=session_id,
            first_ts=first_ts,
            last_ts=last_ts,
            detail=(
                "no record in this file carries a cwd, so it holds no "
                "conversation - it is claude code bookkeeping "
                "(file-history-snapshot, summary or bridge-session "
                "records) stored as a transcript"
                if saw_any
                else "the file holds no parseable json records at all"
            ),
        )

    title_read = read_newest_custom_title(path)
    return TranscriptFacts(
        path=path,
        uuid=uuid,
        status=TRANSCRIPT_READ,
        session_id=session_id,
        cwd=cwd,
        first_ts=first_ts,
        last_ts=last_ts,
        custom_title=title_read.title if title_read.found else None,
        first_user_text=first_user,
    )
