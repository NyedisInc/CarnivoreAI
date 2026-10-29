
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.cplugs.huddle import answers as answer_wire, files, structured, task_files
from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.sdk.storage import CplugStorage

logger = structlog.get_logger()

FOLDER = "swarm_forms"
MAX_FILES = answer_wire.MAX_FILES
VALUE_KEYS = ("value", "choice", "choices", "order", "text", "other", "note", "files", "skipped")


def check(questions: Any) -> Tuple[str, str]:
    if not isinstance(questions, list) or not questions:
        raise TaskManagerInvalid("questions must be a non-empty list")
    return structured.build(None, None, questions)


def _path(storage: CplugStorage, question_id: int) -> Path:
    return Path(storage.path) / FOLDER / f"{int(question_id)}.json"


def stage(storage: CplugStorage, question_id: int, parts: str) -> None:
    target = _path(storage, question_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".stage-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(parts)
        os.replace(temp, target)
    except OSError:
        Path(temp).unlink(missing_ok=True)
        raise


def take(storage: CplugStorage, question_id: int) -> Optional[str]:
    try:
        return _path(storage, question_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def drop(storage: CplugStorage, question_id: int) -> None:
    _path(storage, question_id).unlink(missing_ok=True)


def resolve_files(storage: CplugStorage, item_id: int, answers: Any) -> Any:
    if not isinstance(answers, Mapping):
        return answers
    out: Dict[str, Any] = {}
    for qid, raw in answers.items():
        if not isinstance(raw, Mapping):
            out[qid] = raw
            continue
        if "files" in raw:
            raise TaskManagerInvalid(f"question {qid}: send file_ids, not files")
        answer = {k: v for k, v in raw.items() if k != "file_ids"}
        ids = raw.get("file_ids")
        if ids is not None:
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise TaskManagerInvalid(f"question {qid}: file_ids must be a list of file ids")
            if len(ids) > MAX_FILES:
                raise TaskManagerInvalid(f"question {qid}: at most {MAX_FILES} files")
            folders = task_files.search_dirs(item_id)
            answer["files"] = [str(files.locate(storage, item_id, i, folders).resolve()) for i in dict.fromkeys(ids)]
        out[qid] = answer
    return out


def _words(answer: Mapping[str, Any]) -> str:
    if answer.get("skipped"):
        return "no answer"
    parts: List[str] = []
    if "value" in answer:
        parts.append("yes" if answer["value"] else "no")
    if answer.get("choice"):
        parts.append(str(answer["choice"]))
    if "choices" in answer:
        parts.append(" + ".join(answer["choices"]))
    if "order" in answer:
        parts.append(" > ".join(answer["order"]))
    if answer.get("text"):
        parts.append(answer["text"])
    if answer.get("other"):
        parts.append(f"other: {answer['other']}")
    return ", ".join(parts) or "no answer"


def delivery(questions: Sequence[Mapping[str, Any]], checked: Mapping[str, Mapping[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    lines = [f"answers to {len(questions)} question{'' if len(questions) == 1 else 's'}:"]
    shaped: Dict[str, Any] = {}
    for number, question in enumerate(questions, 1):
        answer = checked.get(question["id"], {"skipped": True})
        shaped[question["id"]] = {k: answer[k] for k in VALUE_KEYS if k in answer}
        line = f"{number}. {_words(answer)}"
        if answer.get("note"):
            line += f", note: {answer['note']}"
        for path in answer.get("files", []):
            line += f", file: {path}"
        lines.append(line)
    extra = checked.get(answer_wire.EXTRA)
    if extra:
        lines.append(answer_wire.extra_line(extra))
        shaped[answer_wire.EXTRA] = {k: extra[k] for k in ("text", "files") if k in extra}
    return "\n".join(lines), shaped


__all__ = ["FOLDER", "MAX_FILES", "check", "delivery", "drop", "resolve_files", "stage", "take"]
