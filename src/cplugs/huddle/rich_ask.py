
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.cplugs.huddle.rules import TaskManagerInvalid

VERSION = 2
TYPED_PREFIX = f'{{"v": {VERSION}'
TYPED_SQL = f"parts LIKE '{{\"v\": {VERSION}%'"
ANSWERS_TO_PREFIX = f'{{"v": {VERSION}, "answers_to"'

YES_NO, SINGLE, MULTI, RANK, SHORT_TEXT, LONG_TEXT = "yes_no", "single", "multi", "rank", "short_text", "long_text"
DATETIME = "datetime"
TYPES = (YES_NO, SINGLE, MULTI, RANK, SHORT_TEXT, LONG_TEXT, DATETIME)
CHOICE_TYPES = (SINGLE, MULTI, RANK)
TEXT_TYPES = (SHORT_TEXT, LONG_TEXT)

MIN_OPTIONS = 2
MAX_OPTIONS = 12
MAX_LABEL = 200
MAX_REASON = 300
MAX_HELP = 300
MAX_PLACEHOLDER = 100
MAX_SHORT = 500
MAX_DATETIME = 40
MAX_COMMAND = 2000
MAX_COMMAND_LANG = 20
COMMAND_ALONE = (
    "a question with a command (the handoff card with its ran it / failed pills) must be the ONLY question in its task_manager_ask, because "
    "tapping a pill answers and sends the form at once; ask the other questions in a separate task_manager_ask"
)
MAX_LONG = 4000
TEXT_LIMITS = {SHORT_TEXT: MAX_SHORT, LONG_TEXT: MAX_LONG, DATETIME: MAX_DATETIME}

_ID = re.compile(r"^[a-z0-9_-]{1,32}$")
_LANG = re.compile(r"^[A-Za-z0-9_+.-]+$")


def is_typed(parts: str) -> bool:
    return parts.startswith(TYPED_PREFIX)


def _fail(qid: str, why: str) -> TaskManagerInvalid:
    return TaskManagerInvalid(f"question {qid}: {why}")


def _text(value: Any, qid: str, label: str, limit: int, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise _fail(qid, f"{label} must be text")
    value = value.strip()
    if required and not value:
        raise _fail(qid, f"{label} is required")
    if len(value) > limit:
        raise _fail(qid, f"{label} is over {limit} characters")
    return value


def _flag(value: Any, qid: str, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _fail(qid, f"{label} must be true or false")
    return value


def _qid(raw: Any, position: int, seen: set) -> str:
    qid = f"q{position}" if raw is None else raw
    if not isinstance(qid, str) or not _ID.match(qid):
        raise TaskManagerInvalid(f"question {position}: id must match [a-z0-9_-] and be 1 to 32 characters")
    if qid in seen:
        raise TaskManagerInvalid(f"question {qid}: duplicate id")
    seen.add(qid)
    return qid


def _options(raw: Any, qid: str, kind: str) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or not MIN_OPTIONS <= len(raw) <= MAX_OPTIONS:
        raise _fail(qid, f"{kind} needs {MIN_OPTIONS} to {MAX_OPTIONS} options")
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for at, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {"label": item}
        if not isinstance(item, Mapping):
            raise _fail(qid, f"option {at} must be a label or an object")
        oid = item.get("id", f"o{at}")
        if not isinstance(oid, str) or not _ID.match(oid) or oid in seen:
            raise _fail(qid, f"option {at}: id must be unique and match [a-z0-9_-], 1 to 32 characters")
        seen.add(oid)
        option: Dict[str, Any] = {"id": oid, "label": _text(item.get("label"), qid, f"option {oid} label", MAX_LABEL)}
        if _flag(item.get("recommended"), qid, f"option {oid} recommended", False):
            if kind == RANK:
                raise _fail(qid, "a rank recommends an order (recommend.order), not an option")
            option["recommended"] = True
        reason = _text(item.get("reason"), qid, f"option {oid} reason", MAX_REASON, required=False)
        if reason:
            option["reason"] = reason
        out.append(option)
    recommended = [o for o in out if o.get("recommended")]
    if kind == SINGLE and len(recommended) > 1:
        raise _fail(qid, "a single choice recommends at most one option")
    return out


def _command(raw: Any, qid: str, kind: str) -> Optional[Dict[str, str]]:
    if raw is None:
        return None
    if kind != SINGLE:
        raise _fail(qid, f"{kind} takes no command (only a single choice does)")
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, Mapping):
        raise _fail(qid, "command must be text or an object {text, lang?}")
    out = {"text": _text(raw.get("text"), qid, "command text", MAX_COMMAND)}
    lang = _text(raw.get("lang"), qid, "command lang", MAX_COMMAND_LANG, required=False)
    if lang:
        if not _LANG.match(lang):
            raise _fail(qid, "command lang must be one short word such as bash or python")
        out["lang"] = lang
    return out


def _recommend(raw: Any, qid: str, kind: str, options: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if kind == DATETIME:
        raise _fail(qid, "a datetime question takes no recommendation")
    if kind in (SINGLE, MULTI):
        raise _fail(qid, "mark the recommended option with recommended: true, not recommend")
    if not isinstance(raw, Mapping):
        raise _fail(qid, "recommend must be an object")
    out: Dict[str, Any] = {}
    if kind == YES_NO:
        if not isinstance(raw.get("value"), bool):
            raise _fail(qid, "recommend.value must be true or false")
        out["value"] = raw["value"]
    elif kind == RANK:
        order = raw.get("order")
        if not isinstance(order, list) or sorted(order, key=str) != sorted((o["id"] for o in options), key=str):
            raise _fail(qid, "recommend.order must list every option id exactly once")
        out["order"] = list(order)
    else:
        out["text"] = _text(raw.get("text"), qid, "recommend.text", TEXT_LIMITS[kind])
    reason = _text(raw.get("reason"), qid, "recommend.reason", MAX_REASON, required=False)
    if reason:
        out["reason"] = reason
    return out


def _question(raw: Any, position: int, seen: set) -> Dict[str, Any]:
    if isinstance(raw, str):
        qid = _qid(None, position, seen)
        return {"id": qid, "type": LONG_TEXT, "prompt": _text(raw, qid, "prompt", 500), "required": False}
    if not isinstance(raw, Mapping):
        raise TaskManagerInvalid(f"question {position}: must be a string or an object")
    qid = _qid(raw.get("id"), position, seen)
    kind = raw.get("type")
    if kind not in TYPES:
        raise _fail(qid, f"type must be one of {', '.join(TYPES)}")
    out: Dict[str, Any] = {"id": qid, "type": kind, "prompt": _text(raw.get("prompt"), qid, "prompt", 500),
                           "required": _flag(raw.get("required"), qid, "required", True)}
    help_text = _text(raw.get("help"), qid, "help", MAX_HELP, required=False)
    if help_text:
        out["help"] = help_text
    command = _command(raw.get("command"), qid, kind)
    if command:
        out["command"] = command
    if kind in CHOICE_TYPES:
        out["options"] = _options(raw.get("options"), qid, kind)
    elif raw.get("options") is not None:
        raise _fail(qid, f"{kind} takes no options")
    if kind in (SINGLE, MULTI):
        out["other"] = _flag(raw.get("other"), qid, "other", False)
    elif raw.get("other") is not None:
        raise _fail(qid, f"{kind} takes no other box")
    if kind == YES_NO and raw.get("labels") is not None:
        labels = raw["labels"]
        if not (isinstance(labels, list) and len(labels) == 2):
            raise _fail(qid, "labels must be two words: [yes label, no label]")
        out["labels"] = [_text(v, qid, "label", 40) for v in labels]
    if kind == MULTI:
        _bounds(raw, out, qid, len(out["options"]))
    if kind in TEXT_TYPES:
        out["max_length"] = _max_length(raw.get("max_length"), qid, kind)
        placeholder = _text(raw.get("placeholder"), qid, "placeholder", MAX_PLACEHOLDER, required=False)
        if placeholder:
            out["placeholder"] = placeholder
    recommend = _recommend(raw.get("recommend"), qid, kind, out.get("options", []))
    if recommend:
        out["recommend"] = recommend
    return out


def _bounds(raw: Mapping[str, Any], out: Dict[str, Any], qid: str, count: int) -> None:
    for name in ("min", "max"):
        value = raw.get(name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= count:
            raise _fail(qid, f"{name} must be a whole number from 0 to {count}")
        out[name] = value
    if "min" in out and "max" in out and out["min"] > out["max"]:
        raise _fail(qid, "min is over max")


def _max_length(value: Any, qid: str, kind: str) -> int:
    limit = TEXT_LIMITS[kind]
    if value is None:
        return limit
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limit:
        raise _fail(qid, f"max_length must be a whole number from 1 to {limit}")
    return value


def normalize(questions: Sequence[Any]) -> Tuple[List[Dict[str, Any]], bool]:
    seen: set = set()
    typed = any(not isinstance(q, str) for q in questions)
    out = [_question(q, at, seen) for at, q in enumerate(questions, 1)]
    _require_command_alone(out)
    return out, typed


def _require_command_alone(questions: Sequence[Mapping[str, Any]]) -> None:
    if len(questions) > 1:
        for question in questions:
            if question.get("command"):
                raise _fail(question["id"], COMMAND_ALONE)


def option_line(question: Mapping[str, Any]) -> List[str]:
    out = []
    for at, option in enumerate(question.get("options", [])):
        mark = ""
        if option.get("recommended"):
            mark = f" (recommended: {option['reason']})" if option.get("reason") else " (recommended)"
        out.append(f"   {chr(ord('a') + at)}. {option['label']}{mark}")
    if question.get("other"):
        out.append("   (or other)")
    return out


def question_lines(number: int, question: Mapping[str, Any]) -> List[str]:
    kind = question["type"]
    notes: List[str] = []
    if kind == YES_NO:
        pair = question.get("labels") or ["yes", "no"]
        notes.append(" / ".join(pair))
        recommend = question.get("recommend")
        if recommend:
            notes.append(f"recommended: {pair[0] if recommend['value'] else pair[1]}")
    elif kind == RANK:
        notes.append("rank in order")
        recommend = question.get("recommend")
        if recommend:
            labels = {o["id"]: o["label"] for o in question["options"]}
            notes.append("recommended: " + " > ".join(labels[i] for i in recommend["order"]))
    elif kind == MULTI:
        notes.append("pick any")
    if not question.get("required", True):
        notes.append("optional")
    head = f"{number}. {question['prompt']}" + (f" ({'; '.join(notes)})" if notes else "")
    command = question.get("command")
    fence = [] if not command else [f"   ```{command.get('lang', '')}", *(f"   {line}" for line in command["text"].splitlines()), "   ```"]
    return [head, *fence, *option_line(question)]


def flatten(context: str, questions: Sequence[Mapping[str, Any]]) -> str:
    lines: List[str] = []
    for number, question in enumerate(questions, 1):
        lines.extend(question_lines(number, question))
    body = "\n".join(lines)
    return f"{context}\n\n{body}" if context else body


def dump(context: str, questions: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps({"v": VERSION, "context": context, "questions": list(questions)}, ensure_ascii=False)


def form_of(raw: str) -> Optional[List[Dict[str, Any]]]:
    if not raw or not is_typed(raw):
        return None
    try:
        data = json.loads(raw)
        return [dict(q) for q in data["questions"]]
    except (ValueError, KeyError, TypeError):
        return None


__all__ = ["TYPED_SQL", "TYPES", "dump", "flatten", "form_of", "is_typed", "normalize"]
