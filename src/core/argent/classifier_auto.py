
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

from src.core.argent import classifier, classifier_signals

logger = structlog.get_logger()


async def run(tmux_name: str, display_name: str, working_dir: str, transcript: Optional[Path], commits: Iterable[Any] = (), *,
              chat: Optional[classifier.ChatFn] = None) -> classifier.Outcome:
    try:
        prompt = await asyncio.to_thread(classifier_signals.last_prompt, transcript)
        files = [f for c in commits for f in c.files]
        signals = await classifier_signals.gather(working_dir, prompt, files)
        outcome = await classifier.classify(tmux_name, signals, chat=chat, display_name=display_name, auto=True)
    except (OSError, ValueError) as exc:
        logger.info("argent_classifier_auto_failed", error_type=type(exc).__name__)
        return classifier.Outcome(reason="read_failed")
    if outcome.action != "none":
        logger.info("argent_classifier_auto", action=outcome.action, confidence=outcome.confidence)
    return outcome
