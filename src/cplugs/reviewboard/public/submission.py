
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.cplugs.sdk.visible_text import TextRefused, clean_json, lines_ok, normalize, visible

MAX_COMMENT = 4000
MAX_NAME = 60
MAX_ANSWERS = 40
MAX_OPTIONS = 12
MAX_DEPTH = 32
_ITEM_ID = re.compile(r"[a-z][a-z0-9_-]{0,31}", re.ASCII)
_POST_ID = re.compile(r"[A-Za-z0-9_-]{8,64}", re.ASCII)
_REVISION = re.compile(r"r[1-9][0-9]{0,5}", re.ASCII)
_ANSWER_KEYS = frozenset({"prompt", "options", "checked", "text", "note"})


class Malformed(ValueError):
    pass


@dataclass(frozen=True)
class Submission:

    kind: str
    client_post_id: str
    name: Optional[str]
    body: Mapping[str, Any]
    texts: Tuple[str, ...]
    revision: Optional[str] = None


def clean_text(value: Any, limit: int, *, single_line: bool = False, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise Malformed("not text")
    text = normalize(value).strip()
    allowed = "" if single_line else "\n\t"
    if len(text) > limit or (not text and not allow_empty):
        raise Malformed("text length")
    if not all(visible(text, allowed)):
        raise Malformed("hidden or control character")
    if not single_line and not lines_ok(text):
        raise Malformed("too many lines")
    return text


def _payload_string(value: str) -> str:
    return clean_text(value, MAX_COMMENT, allow_empty=True)


def _clean_json(value: Any) -> Any:
    try:
        return clean_json(value, _payload_string)
    except TextRefused as exc:
        raise Malformed(str(exc)) from exc


def _depth(value: Any, level: int = 0) -> int:
    if level > MAX_DEPTH or not isinstance(value, (dict, list)):
        return level
    children = value.values() if isinstance(value, dict) else value
    return max((_depth(child, level + 1) for child in children), default=level + 1)


def _strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (str(k), *_strings(v))]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _answer(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict) or not set(raw) <= _ANSWER_KEYS or not isinstance(raw.get("prompt"), str) or not _ITEM_ID.fullmatch(raw["prompt"]):
        raise Malformed("answer shape")
    out: Dict[str, Any] = {"prompt": raw["prompt"]}
    if "options" in raw:
        picks = raw["options"]
        if not isinstance(picks, list) or len(picks) > MAX_OPTIONS or not all(isinstance(p, str) and _ITEM_ID.fullmatch(p) for p in picks):
            raise Malformed("answer options")
        out["options"] = list(picks)
    if "checked" in raw:
        if not isinstance(raw["checked"], bool):
            raise Malformed("answer checked")
        out["checked"] = raw["checked"]
    if "text" in raw:
        out["text"] = clean_text(raw["text"], MAX_COMMENT)
    if "note" in raw:
        out["note"] = clean_text(raw["note"], MAX_COMMENT, allow_empty=True)
    return out


def _common(raw: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
    post_id = raw.get("client_post_id")
    if not isinstance(post_id, str) or not _POST_ID.fullmatch(post_id):
        raise Malformed("client_post_id")
    name = raw.get("name")
    if name is None:
        return post_id, None
    cleaned = clean_text(name, MAX_NAME, single_line=True, allow_empty=True)
    return post_id, cleaned or None


def parse_json(body: bytes) -> Dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"), parse_constant=_no_constant, parse_float=_finite)
    except (UnicodeDecodeError, ValueError) as exc:
        raise Malformed("not json") from exc
    if not isinstance(value, dict):
        raise Malformed("not an object")
    return value


def _finite(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise ValueError("not a finite number")
    return number


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _answer_body(raw: Mapping[str, Any], *, allow_empty: bool) -> Tuple[Dict[str, Any], List[str]]:
    if ("answers" in raw) == ("payload" in raw):
        raise Malformed("answers keys")
    if "payload" in raw:
        payload = raw["payload"]
        if not isinstance(payload, dict) or _depth(payload) > MAX_DEPTH:
            raise Malformed("payload shape")
        cleaned = _clean_json(payload)
        return {"payload": cleaned}, _strings(cleaned)
    given = raw["answers"]
    if not isinstance(given, list) or len(given) > MAX_ANSWERS or (not given and not allow_empty):
        raise Malformed("answers list")
    checked = [_answer(item) for item in given]
    return {"answers": checked}, [a[k] for a in checked for k in ("text", "note") if a.get(k)]


@dataclass(frozen=True)
class Draft:

    revision: str
    body: Mapping[str, Any]
    texts: Tuple[str, ...]


def draft(raw: Mapping[str, Any]) -> Draft:
    if not set(raw) <= {"revision", "answers", "payload"}:
        raise Malformed("draft keys")
    revision = _revision_of(raw, required=True)
    body, texts = _answer_body(raw, allow_empty=True)
    return Draft(str(revision), body, tuple(texts))


def _revision_of(raw: Mapping[str, Any], *, required: bool) -> Optional[str]:
    if "revision" not in raw and not required:
        return None
    revision = raw.get("revision")
    if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
        raise Malformed("revision")
    return revision


def comment(raw: Mapping[str, Any]) -> Submission:
    post_id, name = _common(raw)
    if not set(raw) <= {"client_post_id", "name", "revision", "text", "anchor", "item"} or ("anchor" in raw and "item" in raw):
        raise Malformed("comment keys")
    body: Dict[str, Any] = {"text": clean_text(raw.get("text"), MAX_COMMENT)}
    for key in ("anchor", "item"):
        if key in raw:
            if not isinstance(raw[key], str) or not _ITEM_ID.fullmatch(raw[key]):
                raise Malformed(f"comment {key}")
            body[key] = raw[key]
    return Submission("comment", post_id, name, body, tuple([name] if name else []) + (body["text"],), _revision_of(raw, required=False))
