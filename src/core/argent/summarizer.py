
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

import structlog

from src.core.argent import classifier, writeback_template
from src.core.byoai import registry
from src.core.byoai.contracts import CAP_CHAT, ByoaiError, NotConfigured

logger = structlog.get_logger()

FEATURE_ID = "argent.summary"
LABEL_KEY = "ai.feature.argent_summary"
DESCRIPTION_KEY = "ai.feature.argent_summary.description"
TIMEOUT_SECONDS, MAX_TOKENS = 20.0, 120
SYSTEM = ("You write one plain English sentence, at most 25 words, saying what a coding session just did, from its commit subjects and the "
          "repo-relative files it changed. No names, no quotes, no markdown, no line breaks. Reply with only the sentence.")

ChatFn = Callable[..., Awaitable[Any]]


@dataclass
class Summary:

    text: str = ""
    reason: str = ""
    result: Any = None


def register_feature() -> None:
    if registry.get_feature(FEATURE_ID) is None:
        registry.register_feature(FEATURE_ID, CAP_CHAT, LABEL_KEY, DESCRIPTION_KEY, group=classifier.FEATURE_GROUP)


async def summarize(subjects: Sequence[str], paths: Sequence[str], *, chat: Optional[ChatFn] = None) -> Summary:
    shown = [writeback_template.clean(s, 200) for s in subjects[:20]]
    files = [writeback_template.clean(p, 200) for p in writeback_template.relative_paths(paths)[:30]]
    if not shown and not files:
        return Summary(reason="nothing_to_say")
    found = classifier.has_secret(*shown, *files)
    if found:
        logger.info("argent_summary_blocked_secret", findings=found)
        return Summary(reason="blocked_secret")
    if chat is None:
        from src.core.byoai import gateway

        chat = gateway.chat
    prompt = "commit subjects:\n" + "\n".join(shown) + "\nfiles:\n" + "\n".join(files)
    try:
        result = await asyncio.wait_for(chat(FEATURE_ID, prompt, system=SYSTEM, max_tokens=MAX_TOKENS, temperature=0, timeout_s=TIMEOUT_SECONDS), TIMEOUT_SECONDS)
    except NotConfigured:
        return Summary(reason="no_ai_connection")
    except asyncio.TimeoutError:
        return Summary(reason="ai_timeout")
    except ByoaiError as exc:
        logger.info("argent_summary_ai_failed", error_type=type(exc).__name__)
        return Summary(reason="ai_error")
    return Summary(text=writeback_template.clean(getattr(result, "text", "") or "", 300), result=result)
