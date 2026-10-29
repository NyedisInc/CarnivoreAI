
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.approvals.bounds import fit_text, one_line
from src.core.approvals.extract import KIND_ASK, ROLE_OPTION, ROLE_OTHER, Dialog, squash
from src.core.attention.evidence import observed_conversation_uuid
from src.core.attention.turn_counts import content_blocks
from src.core.timers.redact import redact

logger = structlog.get_logger()

TAIL_BYTES: int = 2 * 1024 * 1024
DESCRIPTION_MAX_CHARS: int = 1000
PREVIEW_MAX_CHARS: int = 4000
LABEL_PREFIX: int = 24
LABEL_MAX_CHARS: int = 500
QUESTION_MAX_CHARS: int = 2000
MAX_OPTIONS: int = 50
MAX_QUESTIONS: int = 8

STATE_MATCHED = "matched"
STATE_NO_TRANSCRIPT = "no_transcript"
STATE_NO_QUESTIONS = "no_questions"
STATE_MISMATCH = "mismatch"


@dataclass(frozen=True)
class AskOption:

    label: str
    description: str = ""
    preview: Optional[str] = None


@dataclass(frozen=True)
class AskQuestion:

    question: str
    header: str
    multi_select: bool
    options: Tuple[AskOption, ...]

    @property
    def has_preview(self) -> bool:
        return any(o.preview for o in self.options)


@dataclass(frozen=True)
class AskQuestions:

    tool_use_id: str
    questions: Tuple[AskQuestion, ...]

    @property
    def fingerprint(self) -> str:
        shape = [self.tool_use_id, [[q.question, q.multi_select, [o.label for o in q.options]] for q in self.questions]]
        return hashlib.sha256(json.dumps(shape, ensure_ascii=False).encode("utf-8")).hexdigest()

    def to_dicts(self) -> List[Dict[str, Any]]:
        return [{"header": fit_text(redact(q.header), 200), "question": fit_text(redact(q.question), QUESTION_MAX_CHARS), "multi_select": q.multi_select,
                 "options": [{"label": fit_text(one_line(o.label), LABEL_MAX_CHARS), "description": redact(o.description)[:DESCRIPTION_MAX_CHARS],
                              "preview": None if o.preview is None else redact(o.preview)[:PREVIEW_MAX_CHARS]}
                             for o in q.options[:MAX_OPTIONS]]} for q in self.questions]


def parse_questions_input(tool_input: Any) -> Optional[Tuple[AskQuestion, ...]]:
    raw = tool_input.get("questions") if isinstance(tool_input, dict) else None
    if not isinstance(raw, list) or not raw:
        return None
    out: List[AskQuestion] = []
    for item in raw:
        options = item.get("options") if isinstance(item, dict) else None
        if not (isinstance(item, dict) and isinstance(item.get("question"), str) and item["question"].strip()
                and isinstance(options, list) and options):
            return None
        built: List[AskOption] = []
        for opt in options:
            if not (isinstance(opt, dict) and isinstance(opt.get("label"), str) and opt["label"].strip()):
                return None
            desc, preview = opt.get("description"), opt.get("preview")
            built.append(AskOption(opt["label"], desc if isinstance(desc, str) else "",
                                   preview if isinstance(preview, str) and preview else None))
        header = item.get("header")
        out.append(AskQuestion(item["question"], header if isinstance(header, str) else "",
                               item.get("multiSelect") is True, tuple(built)))
    return tuple(out)


def questions_in_lines(lines: List[bytes]) -> Optional[AskQuestions]:
    for line in reversed(lines):
        if b"AskUserQuestion" not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        for block in reversed(content_blocks(record, "tool_use")):
            if block.get("name") != "AskUserQuestion":
                continue
            questions = parse_questions_input(block.get("input"))
            if questions is not None:
                return AskQuestions(str(block.get("id") or ""), questions)
    return None


_CACHE: Dict[Tuple[str, int, int], Optional[AskQuestions]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 32


def last_ask_questions(path: Path) -> Optional[AskQuestions]:
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with _CACHE_LOCK:
            if key in _CACHE:
                return _CACHE[key]
        with path.open("rb") as handle:
            start = max(0, stat.st_size - TAIL_BYTES)
            handle.seek(start)
            data = handle.read()
    except OSError as exc:
        logger.warning("ask_questions_unreadable", error_type=type(exc).__name__)
        return None
    lines = data.split(b"\n")
    if start:
        lines = lines[1:]
    found = questions_in_lines(lines)
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = found
    return found


def prefix(text: str) -> str:
    return squash(text.rstrip().removesuffix("✔"))[:LABEL_PREFIX]


def option_rows(dialog: Dialog, question: AskQuestion) -> Optional[Tuple[List[int], Optional[int]]]:
    rows = [i for i, r in enumerate(dialog.rows) if r.role in (ROLE_OPTION, ROLE_OTHER)]
    want = [prefix(o.label) for o in question.options]
    if len(rows) == len(want) + 1 and not question.has_preview:
        other: Optional[int] = rows[-1]
        rows = rows[:-1]
    elif len(rows) == len(want):
        other = None
    else:
        return None
    if [prefix(dialog.rows[i].label) for i in rows] != want:
        return None
    return rows, other


def matching_question(dialog: Dialog, questions: AskQuestions) -> Optional[int]:
    want = squash(dialog.question)
    hits = [i for i, q in enumerate(questions.questions) if squash(redact(q.question)) == want]
    if len(hits) != 1 or option_rows(dialog, questions.questions[hits[0]]) is None:
        return None
    return hits[0]


def serve_fields(dialog: Dialog, asked: Optional[AskQuestions], located: bool) -> Dict[str, Any]:
    if dialog.kind != KIND_ASK or dialog.startup_kind is not None:
        return {}
    if not located:
        state = STATE_NO_TRANSCRIPT
    elif asked is None:
        state = STATE_NO_QUESTIONS
    else:
        at = matching_question(dialog, asked) if len(asked.questions) <= MAX_QUESTIONS else None
        if at is not None:
            return {"questions": asked.to_dicts(), "questions_fingerprint": asked.fingerprint,
                    "questions_state": STATE_MATCHED, "question_index": at + 1,
                    "question_total": len(asked.questions)}
        state = STATE_MISMATCH
    return {"questions": [], "questions_fingerprint": None, "questions_state": state}


_PATHS: Dict[str, Tuple[Optional[Path], float]] = {}
NOT_FOUND_SECONDS: float = 10.0


def _cached_path(uuid: str) -> Tuple[bool, Optional[Path]]:
    with _CACHE_LOCK:
        path, at = _PATHS.get(uuid, (None, 0.0))
        if len(_PATHS) > _CACHE_MAX * 4:
            _PATHS.clear()
    if path is not None:
        return (True, path) if path.is_file() else (False, None)
    return (at > 0 and time.monotonic() - at < NOT_FOUND_SECONDS), None


def locate_ask(info: Any, watcher: Optional[Any]) -> Tuple[Optional[AskQuestions], bool]:
    from src.core.session_token_usage import claude_reader
    from src.core.session_transcript_presence import CONVERSATION_PRESENT

    uuid = info.claude_session_uuid
    observation = watcher.observation_for(info.session.id, now=datetime.now(timezone.utc)) if watcher is not None else None
    if observation is not None and not observation.stale:
        uuid = observed_conversation_uuid(observation.evidence) or uuid
    if not uuid:
        return None, False
    known, path = _cached_path(uuid)
    if not known:
        location = claude_reader.locate_transcript(uuid, working_dir=info.session.working_dir)
        found = Path(location.path) if location.outcome == CONVERSATION_PRESENT and location.path is not None else None
        with _CACHE_LOCK:
            _PATHS[uuid] = (found, time.monotonic())
        path = found
    return (last_ask_questions(path), True) if path is not None else (None, False)


async def served_fields(info: Any, watcher: Optional[Any], dialog: Dialog) -> Dict[str, Any]:
    if dialog.kind != KIND_ASK or dialog.startup_kind is not None:
        return {}
    asked, located = await asyncio.to_thread(locate_ask, info, watcher)
    return serve_fields(dialog, asked, located)
