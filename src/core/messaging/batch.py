
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import List, Mapping, Optional, Sequence, Tuple

from src.core.messaging.accept import clean_body

MAX_LINE_CHARS = 4000

OFFLINE_AFTER_SECONDS = 120.0

FRESH_SECONDS = 120.0

WAIT_DIALOG = "dialog"
WAIT_ASLEEP = "asleep"
WAIT_NOT_RUNNING = "not_running"


@dataclass(frozen=True)
class Pending:

    row_id: str
    text: str
    sent_at: Optional[float]
    received_at: float
    waited: Optional[str] = None
    has_attachments: bool = False


@dataclass(frozen=True)
class Part:

    text: str
    row_ids: Tuple[str, ...]


def _fmt(template: str, **values: object) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def age_text(seconds: float, copy: Mapping[str, str]) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return copy["messaging.batch.age_now"]
    minutes, hours, days = total // 60, total // 3600, total // 86400
    if hours < 1:
        return _fmt(copy["messaging.batch.age_minutes"], m=minutes)
    if days < 1:
        return _fmt(copy["messaging.batch.age_hours"], h=hours, m=minutes % 60)
    return _fmt(copy["messaging.batch.age_days"], d=days, h=hours % 24)


def line_body(row: Pending, copy: Mapping[str, str]) -> str:
    text = clean_body(row.text)
    if len(text) > MAX_LINE_CHARS:
        text = text[:MAX_LINE_CHARS] + " " + copy["messaging.batch.cut"]
    if row.has_attachments:
        text = (text + " " if text else "") + copy["messaging.batch.attachment"]
    return text


def _why(row: Pending, copy: Mapping[str, str]) -> Optional[str]:
    if row.sent_at is not None and row.received_at - row.sent_at > OFFLINE_AFTER_SECONDS:
        return copy["messaging.batch.offline"]
    return {WAIT_DIALOG: copy["messaging.batch.held_dialog"], WAIT_ASLEEP: copy["messaging.batch.held_asleep"],
            WAIT_NOT_RUNNING: copy["messaging.batch.held_not_running"]}.get(row.waited or "")


def dated_line(row: Pending, now: float, tz: Optional[tzinfo], copy: Mapping[str, str]) -> str:
    when = row.sent_at if row.sent_at is not None else row.received_at
    stamp = datetime.fromtimestamp(when, tz).strftime("%a %m/%d %H:%M").lower()
    parts = [stamp, age_text(now - when, copy)]
    why = _why(row, copy)
    if why:
        parts.append(why)
    return f"[{', '.join(parts)}] {line_body(row, copy)}"


def ordered(rows: Sequence[Pending]) -> List[Pending]:
    return sorted(rows, key=lambda r: (r.sent_at if r.sent_at is not None else r.received_at, r.received_at, r.row_id))


def render(rows: Sequence[Pending], *, now: float, tz: Optional[tzinfo], copy: Mapping[str, str], owner: str,
           provider: str, can_reply: bool, max_bytes: int) -> List[Part]:
    items = ordered(rows)
    if not items:
        return []
    names = {"owner": owner, "provider": provider}
    hint = copy["messaging.envelope.reply_hint"] if can_reply else ""
    lone = items[0]
    lone_when = lone.sent_at if lone.sent_at is not None else lone.received_at
    if len(items) == 1 and lone.waited is None and _why(lone, copy) is None and now - lone_when < FRESH_SECONDS:
        head = _fmt(copy["messaging.envelope.single"], **names)
        return [Part("\n".join(x for x in (head + (" " + hint if hint else ""), line_body(lone, copy)) if x),
                     (lone.row_id,))]
    key = "messaging.envelope.batch_header" if len(items) > 1 else "messaging.envelope.batch_header_one"
    header = _fmt(copy[key], count=len(items), **names)
    lines = [(r.row_id, dated_line(r, now, tz, copy)) for r in items]
    parts: List[Part] = []
    current: List[Tuple[str, str]] = []

    def body(chunk: List[Tuple[str, str]], last: bool) -> str:
        return "\n".join([header] + [text for _, text in chunk] + ([hint] if last and hint else []))

    for row_id, text in lines:
        trial = current + [(row_id, text)]
        if current and len(body(trial, True).encode("utf-8")) > max_bytes:
            parts.append(Part(body(current, False), tuple(r for r, _ in current)))
            current = [(row_id, text)]
        else:
            current = trial
    parts.append(Part(body(current, True), tuple(r for r, _ in current)))
    return parts
