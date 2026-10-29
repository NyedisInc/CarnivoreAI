
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.cplugs.huddle import rich_ask
from src.cplugs.huddle.rich_ask import MULTI, RANK, SINGLE, YES_NO
from src.cplugs.huddle.rules import TaskManagerInvalid

MAX_NOTE = 500
MAX_OTHER = 500
ANSWERS_TO = "answers_to"
EXTRA = "_extra"
MAX_EXTRA = 4000


def _clean(value: Any, qid: str, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise TaskManagerInvalid(f"question {qid}: {label} must be text")
    value = value.strip()
    if len(value) > limit:
        raise TaskManagerInvalid(f"question {qid}: {label} is over {limit} characters")
    return value


def _ids(value: Any, qid: str, label: str, valid: Sequence[str]) -> List[str]:
    if not isinstance(value, list) or len(set(value)) != len(value) or any(v not in valid for v in value):
        raise TaskManagerInvalid(f"question {qid}: {label} must list known option ids once each")
    return list(value)


def _one(question: Mapping[str, Any], raw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    qid, kind = question["id"], question["type"]
    options = {o["id"]: o["label"] for o in question.get("options", [])}
    out: Dict[str, Any]
    if kind == YES_NO:
        if raw.get("value") is None:
            return None
        if not isinstance(raw["value"], bool):
            raise TaskManagerInvalid(f"question {qid}: value must be true or false")
        pair = question.get("labels") or ["yes", "no"]
        out = {"value": raw["value"], "label": pair[0] if raw["value"] else pair[1]}
    elif kind == SINGLE:
        choice, other = raw.get("choice"), raw.get("other")
        if choice is not None:
            if choice not in options:
                raise TaskManagerInvalid(f"question {qid}: choice must be a known option id")
            out = {"choice": choice, "label": options[choice]}
        elif other:
            if not question.get("other"):
                raise TaskManagerInvalid(f"question {qid}: has no other box")
            out = {"choice": None, "other": _clean(other, qid, "other", MAX_OTHER)}
        else:
            return None
    elif kind == MULTI:
        picks = _ids(raw.get("choices", []), qid, "choices", list(options))
        other = _clean(raw["other"], qid, "other", MAX_OTHER) if raw.get("other") else ""
        if other and not question.get("other"):
            raise TaskManagerInvalid(f"question {qid}: has no other box")
        if not picks and not other:
            return None
        for name, bad in (("min", len(picks) < question.get("min", 0)), ("max", len(picks) > question.get("max", len(options)))):
            if bad:
                raise TaskManagerInvalid(f"question {qid}: pick {'at least' if name == 'min' else 'at most'} {question[name]}")
        out = {"choices": picks, "labels": [options[p] for p in picks], **({"other": other} if other else {})}
    elif kind == RANK:
        if raw.get("order") is None:
            return None
        order = _ids(raw["order"], qid, "order", list(options))
        if len(order) != len(options):
            raise TaskManagerInvalid(f"question {qid}: order must rank every option")
        out = {"order": order, "labels": [options[o] for o in order]}
    else:
        text = _clean(raw["text"], qid, "text", question.get("max_length", rich_ask.TEXT_LIMITS[kind])) if raw.get("text") is not None else ""
        if not text:
            return None
        out = {"text": text}
    return out


def _recommended(question: Mapping[str, Any], answer: Mapping[str, Any]) -> Optional[bool]:
    kind, recommend = question["type"], question.get("recommend")
    if kind == SINGLE:
        picked = [o["id"] for o in question["options"] if o.get("recommended")]
        return None if not picked else answer.get("choice") == picked[0]
    if kind == MULTI:
        picked = [o["id"] for o in question["options"] if o.get("recommended")]
        return None if not picked else sorted(answer.get("choices", [])) == sorted(picked) and not answer.get("other")
    if not recommend:
        return None
    if kind == YES_NO:
        return answer.get("value") == recommend["value"]
    if kind == RANK:
        return answer.get("order") == recommend["order"]
    return answer.get("text") == recommend.get("text")


def validate(questions: Sequence[Mapping[str, Any]], answers: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(answers, Mapping):
        raise TaskManagerInvalid("answers must be an object keyed by question id")
    extra = _extra(answers.get(EXTRA))
    answers = {k: v for k, v in answers.items() if k != EXTRA}
    known = {q["id"] for q in questions}
    unknown = sorted(set(answers) - known)
    if unknown:
        raise TaskManagerInvalid(f"no such question: {', '.join(unknown)}")
    out: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    for question in questions:
        raw = answers.get(question["id"])
        if raw is not None and not isinstance(raw, Mapping):
            raise TaskManagerInvalid(f"question {question['id']}: the answer must be an object")
        raw = raw or {}
        note = _clean(raw["note"], question["id"], "note", MAX_NOTE) if raw.get("note") is not None else ""
        deliberate = raw.get("skipped") is True
        answer = None if deliberate else _one(question, raw)
        if answer is None:
            if question.get("required", True) and not deliberate:
                missing.append(question["id"])
                continue
            answer = {"skipped": True}
            if deliberate and raw.get("dismissed") is True:
                answer["dismissed"] = True
        else:
            verdict = _recommended(question, answer)
            if verdict is not None:
                answer["recommended"] = verdict
        if note:
            answer["note"] = note
        out[question["id"]] = {**answer, "prompt": question["prompt"]}
    if missing:
        raise TaskManagerInvalid(f"required questions left unanswered: {', '.join(missing)}")
    if extra:
        out[EXTRA] = {"text": extra}
    return out


def _extra(raw: Any) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, Mapping) or not isinstance(raw.get("text", ""), str):
        raise TaskManagerInvalid(f"{EXTRA} must be {{text}}")
    text = raw.get("text", "").strip()
    if len(text) > MAX_EXTRA:
        raise TaskManagerInvalid(f"{EXTRA}: over {MAX_EXTRA} characters")
    return text


def _words(answer: Mapping[str, Any]) -> str:
    if answer.get("skipped"):
        return "dismissed" if answer.get("dismissed") else "skipped"
    if "order" in answer:
        return " > ".join(answer["labels"])
    parts: List[str] = []
    if "labels" in answer and "order" not in answer:
        parts.extend(answer["labels"])
    elif "label" in answer:
        parts.append(answer["label"])
    if "text" in answer:
        parts.append(answer["text"])
    if answer.get("other"):
        parts.append(f"other: {answer['other']}")
    return ", ".join(parts)


def text_of(questions: Sequence[Mapping[str, Any]], answers: Mapping[str, Mapping[str, Any]]) -> str:
    lines = [f"answers to {len(questions)} question{'' if len(questions) == 1 else 's'}:"]
    for number, question in enumerate(questions, 1):
        answer = answers[question["id"]]
        line = f"{number}. {question['prompt']} {_words(answer)}"
        if answer.get("recommended") is True:
            line += " (recommended)"
        elif answer.get("recommended") is False:
            line += " (not the recommendation)"
        if answer.get("note"):
            line += f"; note: {answer['note']}"
        lines.append(line)
    if answers.get(EXTRA):
        lines.append(f"anything else: {answers[EXTRA]['text']}")
    return "\n".join(lines)


def lines_of(answers: Mapping[str, Mapping[str, Any]]) -> List[str]:
    questions = [(qid, a) for qid, a in answers.items() if qid != EXTRA]
    lines = [f"{n}. {a.get('prompt', qid)}: {_words(a)}" for n, (qid, a) in enumerate(questions, 1)]
    if answers.get(EXTRA):
        lines.append(f"anything else: {answers[EXTRA]['text']}")
    return lines


def dump(question_id: int, answers: Mapping[str, Any]) -> str:
    return json.dumps({"v": rich_ask.VERSION, ANSWERS_TO: question_id, "answers": answers}, ensure_ascii=False)


def wire(raw: str) -> Optional[Dict[str, Any]]:
    if not raw or not raw.startswith('{"v": 2, "answers_to"'):
        return None
    try:
        data = json.loads(raw)
        if data.get("freeform"):
            return {ANSWERS_TO: int(data[ANSWERS_TO]), "freeform": True}
        return {ANSWERS_TO: int(data[ANSWERS_TO]), "answers": dict(data["answers"])}
    except (ValueError, KeyError, TypeError):
        return None


__all__ = ["ANSWERS_TO", "EXTRA", "dump", "lines_of", "text_of", "validate", "wire"]
