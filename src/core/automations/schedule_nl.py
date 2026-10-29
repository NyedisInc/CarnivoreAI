
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from src.core.automations import models as m, schedule
from src.core.byoai import registry
from src.core.byoai.contracts import CAP_CHAT, ByoaiError, NotConfigured

logger = structlog.get_logger()

FEATURE_ID = "automations.schedule"
LABEL_KEY = "ai.feature.automations_schedule"
DESCRIPTION_KEY = "ai.feature.automations_schedule.description"
FEATURE_GROUP = "automations"
TIMEOUT_SECONDS = 15.0
MAX_TOKENS = 2000
MAX_TEXT = 200

ChatFn = Callable[..., Awaitable[Any]]

_SYSTEM = (
    "You turn a plain-English schedule into one five-field cron expression: minute hour day-of-month month day-of-week. "
    "Times are wall-clock in the IANA zone you are given. Allowed: numbers, names (jan, mon), lists (1,15), ranges (1-5), steps "
    "(*/15). The day-of-week field also takes DOW#N for the Nth weekday of the month (N 1 to 5), so 'every third Tuesday at 5 PM' "
    "is '0 17 * * 2#3' (0 or 7 is Sunday). '#' is allowed only in day-of-week. Never put a restricted day-of-month and a "
    "restricted day-of-week together: cron then fires on either. No @daily, no seconds, no L, no W. Fires must be at least 15 "
    "minutes apart. If the sentence cannot be said in this grammar, refuse; never approximate. Reply with ONLY a JSON object: "
    '{"cron": "<expression>", "explain": "<one plain sentence saying when it fires>"} or {"refuse": "<short plain reason>"}.'
)

_MESSAGES = {
    "no_ai_connection": "no AI connection is set up for this, add one in settings, ai",
    "ai_timeout": "the AI did not answer in time",
    "ai_error": "the AI call failed",
    "ai_output_invalid": "the AI did not answer with a usable schedule",
    "ai_refused": "that schedule cannot be written as a cron",
    "text_empty": "write when it should run",
    "timezone_invalid": "that time zone name is not known",
}


def register_feature() -> None:
    if registry.get_feature(FEATURE_ID) is None:
        registry.register_feature(FEATURE_ID, CAP_CHAT, LABEL_KEY, DESCRIPTION_KEY, group=FEATURE_GROUP)


def refusal(reason: str, message: Optional[str] = None) -> Dict[str, Any]:
    return {"ok": False, "reason": reason, "message": message or _MESSAGES.get(reason, reason)}


def _first_object(text: str) -> Optional[Dict[str, Any]]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(re.sub(r"[\x00-\x08\x0b-\x1f]", " ", text[start:end + 1]))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


async def interpret(text: str, zone: str, *, chat: ChatFn, timeout: float = TIMEOUT_SECONDS) -> Dict[str, Any]:
    sentence = " ".join(text.split())[:MAX_TEXT]
    if not sentence:
        return refusal("text_empty")
    prompt = json.dumps({"schedule": sentence, "timezone": zone})
    try:
        result = await asyncio.wait_for(
            chat(FEATURE_ID, prompt, system=_SYSTEM, max_tokens=MAX_TOKENS, temperature=0, timeout_s=timeout), timeout)
    except asyncio.TimeoutError:
        return refusal("ai_timeout")
    except NotConfigured:
        return refusal("no_ai_connection")
    except ByoaiError as exc:
        logger.info("automations_schedule_ai_failed", error=type(exc).__name__)
        return refusal("ai_error")
    answer = _first_object(getattr(result, "text", "") or "")
    if answer is None:
        return refusal("ai_output_invalid")
    if isinstance(answer.get("refuse"), str):
        return refusal("ai_refused", answer["refuse"].strip()[:200] or None)
    cron, explain = answer.get("cron"), answer.get("explain")
    if not isinstance(cron, str) or not cron.strip() or len(cron) > 120:
        return refusal("ai_output_invalid")
    cron = " ".join(cron.split())
    try:
        schedule.compile_cron(cron, time.time())
    except m.AutomationInvalid as exc:
        return refusal(exc.code, str(exc)[:200])
    return {"ok": True, "cron": cron, "explain": explain.strip()[:300] if isinstance(explain, str) else ""}
