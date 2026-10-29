
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Tuple

import structlog

from src.core.skill_fires.parse import HARNESS_CLAUDE, parse_claude_line
from src.core.skill_watch.classify import classify_call
from src.core.subagents.scan_inputs import AgentFilesSignature, agent_files_signature
from src.core.timers.redact import redact

logger = structlog.get_logger(__name__)

SubsSeen = Tuple[AgentFilesSignature, Optional[str], Optional[str]]

MAX_SPAN_BYTES = 4 * 1024 * 1024
MAX_SPAN_LINES = 3000
MAX_LINE = 1024 * 1024
EXCERPT_CHARS = 140

ENDED_HUMAN = "human"
ENDED_EOF = "eof"
ENDED_CAP = "cap"
ENDED_FIRE = "fire"
MAX_SUBAGENT_FILES = 32

_INTERRUPT = "[Request interrupted by user"
_NOT_HUMAN_PREFIXES = ("<local-command-", "<task-notification", "<system-reminder", "Caveat:",
                       "<command-message>", "<bash-")
_CORRECTION = re.compile(
    r"^\W*(?:no\b|nope\b|wrong\b|stop\b|don'?t\b|do not\b|undo\b|revert\b|wait\b|actually\b"
    r"|instead\b|that'?s (?:not|wrong)\b|not what\b)"
    r"|that'?s not what|you (?:didn'?t|forgot|broke|missed|ignored)\b|why did you\b|i (?:said|asked)\b")


@dataclass
class SpanFacts:

    tool_calls: int = 0
    tool_errors: int = 0
    interrupts: int = 0
    tokens: Optional[int] = None
    correction: Optional[bool] = None
    next_excerpt: Optional[str] = None
    ended: str = ENDED_EOF
    categories: Dict[str, int] = field(default_factory=dict)
    cwd: Optional[str] = None


def _blocks(record: Dict[str, Any]) -> Any:
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _human_text(content: Any) -> Optional[str]:
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        parts = [b["text"] for b in content
                 if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
    else:
        return None
    text = "\n".join(parts).strip()
    if not text or text.startswith(_INTERRUPT) or text.startswith(_NOT_HUMAN_PREFIXES):
        return None
    return text


def redact_excerpt(text: str) -> str:
    return " ".join(redact(text[:2000]).split())[:EXCERPT_CHARS]


def _take_usage(record: Dict[str, Any], seen: Dict[str, int]) -> None:
    message = record.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return
    total = 0
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total += value
    key = message.get("id") if isinstance(message.get("id"), str) else f"line{len(seen)}"
    seen[key] = total


def _apply(record: Dict[str, Any], facts: SpanFacts, tokens: Dict[str, int], first: bool) -> bool:
    kind = record.get("type")
    content = _blocks(record)
    if record.get("isSidechain") is True:
        for block in content if kind == "assistant" and isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                for category in classify_call(str(block.get("name") or ""), block.get("input")):
                    facts.categories[category] = facts.categories.get(category, 0) + 1
        return False
    if kind == "assistant":
        _take_usage(record, tokens)
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                facts.tool_calls += 1
                for category in classify_call(str(block.get("name") or ""), block.get("input")):
                    facts.categories[category] = facts.categories.get(category, 0) + 1
        return False
    if kind != "user" or record.get("isMeta") is True:
        return False
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error") is True:
                facts.tool_errors += 1
    raw = content if isinstance(content, str) else " ".join(
        b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)
    ) if isinstance(content, list) else ""
    if raw.lstrip().startswith(_INTERRUPT):
        facts.interrupts += 1
        return False
    text = _human_text(content)
    if text is None or first:
        return False
    facts.correction = bool(_CORRECTION.search(text[:240].lower()))
    facts.next_excerpt = redact_excerpt(text) if facts.correction else None
    return True


@dataclass
class SpanState:

    offset: int
    pos: int = 0
    inode: Optional[int] = None
    facts: SpanFacts = field(default_factory=SpanFacts)
    tokens: Dict[str, int] = field(default_factory=dict)
    read: int = 0
    lines: int = 0
    first: bool = True
    done: bool = False
    subs_final: bool = False
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    cwd: Optional[str] = None
    sub_read: int = 0
    subs: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    subs_seen: Optional[SubsSeen] = None

    def __post_init__(self) -> None:
        self.pos = self.pos or self.offset


def new_state(offset: int) -> SpanState:
    return SpanState(offset=offset)


def _epoch(stamp: Optional[str]) -> Optional[float]:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() if stamp else None
    except ValueError:
        return None


def _read_main(path: str, state: SpanState) -> bool:
    facts = state.facts
    with open(path, "rb") as handle:
        handle.seek(state.pos)
        while not state.done:
            if state.read >= MAX_SPAN_BYTES or state.lines >= MAX_SPAN_LINES:
                facts.ended, state.done = ENDED_CAP, True
                break
            line = handle.readline(MAX_LINE + 1)
            if not line:
                break
            state.read += len(line)
            if not line.endswith(b"\n") and len(line) <= MAX_LINE:
                state.read -= len(line)
                break
            if len(line) > MAX_LINE:
                while not line.endswith(b"\n") and state.read < MAX_SPAN_BYTES:
                    line = handle.readline(MAX_LINE)
                    state.read += len(line)
                    if not line:
                        break
                state.first = False
                state.pos = handle.tell()
                continue
            state.lines += 1
            state.pos = handle.tell()
            try:
                record = json.loads(line)
            except ValueError:
                state.first = False
                continue
            if not isinstance(record, dict):
                state.first = False
                continue
            stamp = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
            if state.first:
                state.start_ts = stamp
                state.cwd = record.get("cwd") if isinstance(record.get("cwd"), str) else None
            elif parse_claude_line(line):
                facts.ended, state.end_ts, state.done = ENDED_FIRE, stamp, True
                break
            if _apply(record, facts, state.tokens, state.first):
                facts.ended, state.end_ts, state.done = ENDED_HUMAN, stamp, True
                break
            state.first = False
    return True


def _unchanged_files(files: AgentFilesSignature, state: SpanState) -> FrozenSet[str]:
    prior = state.subs_seen
    if files is None or prior is None or prior[1] != state.start_ts:
        return frozenset()
    before = dict(prior[0] or ())
    return frozenset(name for name, times in files if times is not None and before.get(name) == times)


def _read_subagents(path: str, state: SpanState) -> None:
    root = os.path.join(path[:-6] if path.endswith(".jsonl") else path, "subagents")
    listed = agent_files_signature(Path(root))
    if listed is None:
        return
    files = tuple(entry for entry in listed if entry[0].endswith(".jsonl"))
    if state.subs_seen == (files, state.start_ts, state.end_ts):
        return
    names = [name for name, _ in files]
    failed = set()
    start = _epoch(state.start_ts)
    unchanged = _unchanged_files(files, state)
    for name in names[:MAX_SUBAGENT_FILES]:
        if state.sub_read >= MAX_SPAN_BYTES:
            break
        if name in unchanged:
            continue
        fpath = os.path.join(root, name)
        try:
            fd = os.open(fpath, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            failed.add(name)
            continue
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                continue
            prev = state.subs.get(fpath)
            pos = prev[1] if prev and prev[0] == info.st_ino and info.st_size >= prev[1] else 0
            if pos == 0 and start is not None and info.st_mtime < start:
                continue
            with os.fdopen(os.dup(fd), "rb") as handle:
                handle.seek(pos)
                while state.sub_read < MAX_SPAN_BYTES:
                    line = handle.readline(MAX_LINE + 1)
                    if not line or (not line.endswith(b"\n") and len(line) <= MAX_LINE):
                        break
                    state.sub_read += len(line)
                    pos = handle.tell()
                    if len(line) > MAX_LINE:
                        while not line.endswith(b"\n") and state.sub_read < MAX_SPAN_BYTES:
                            line = handle.readline(MAX_LINE)
                            state.sub_read += len(line)
                            if not line:
                                break
                        pos = handle.tell()
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(record, dict) or record.get("type") != "assistant":
                        continue
                    stamp = record.get("timestamp")
                    if isinstance(stamp, str) and ((state.start_ts and stamp < state.start_ts)
                                                   or (state.end_ts and stamp > state.end_ts)):
                        continue
                    content = _blocks(record)
                    for block in content if isinstance(content, list) else []:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            for category in classify_call(str(block.get("name") or ""), block.get("input")):
                                state.facts.categories[category] = state.facts.categories.get(category, 0) + 1
            state.subs[fpath] = (info.st_ino, pos)
        except OSError as exc:
            failed.add(name)
            logger.debug("skill_subagent_unreadable", error_type=type(exc).__name__)
        finally:
            os.close(fd)
    kept = tuple(entry for entry in files if entry[0] not in failed)
    state.subs_seen = (kept, state.start_ts, state.end_ts)


def advance(path: str, state: SpanState) -> bool:
    try:
        info = os.stat(path)
        if state.inode is not None and (info.st_ino != state.inode or info.st_size < state.pos):
            state.__dict__.update(new_state(state.offset).__dict__)
        state.inode = info.st_ino
        if not state.done:
            _read_main(path, state)
        if not state.subs_final:
            _read_subagents(path, state)
            state.subs_final = state.done
    except OSError as exc:
        logger.debug("skill_span_unreadable", error_type=type(exc).__name__)
        return False
    state.facts.tokens = sum(state.tokens.values()) if state.tokens else None
    state.facts.cwd = state.cwd
    return True


def read_span(path: str, offset: int, harness: str) -> Optional[SpanFacts]:
    if harness != HARNESS_CLAUDE:
        return None
    state = new_state(offset)
    return state.facts if advance(path, state) else None
