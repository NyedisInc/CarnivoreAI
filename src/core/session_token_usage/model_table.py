
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ModelPrices:

    input: float
    cache_write: float
    cache_read: float
    output: float


@dataclass(frozen=True)
class ModelFacts:

    window_tokens: Optional[int]
    prices: Optional[ModelPrices]
    display_name: Optional[str] = None


MODEL_TABLE: Dict[str, ModelFacts] = {
    "claude-fable-5-1": ModelFacts(1_000_000, ModelPrices(10.0, 12.5, 0.25, 50.0), "Fable 5.1"),
    "claude-fable-5": ModelFacts(1_000_000, ModelPrices(10.0, 12.5, 1.0, 50.0), "Fable 5"),
    "claude-mythos-5-1": ModelFacts(1_000_000, ModelPrices(10.0, 12.5, 0.25, 50.0), "Mythos 5.1"),
    "claude-mythos-5": ModelFacts(1_000_000, ModelPrices(10.0, 12.5, 1.0, 50.0), "Mythos 5"),
    "claude-opus-5-5": ModelFacts(1_000_000, ModelPrices(4.0, 5.0, 0.2, 20.0), "Opus 5.5"),
    "claude-opus-5": ModelFacts(1_000_000, ModelPrices(5.0, 6.25, 0.5, 25.0), "Opus 5"),
    "claude-opus-4-8": ModelFacts(1_000_000, ModelPrices(5.0, 6.25, 0.5, 25.0), "Opus 4.8"),
    "claude-opus-4-7": ModelFacts(1_000_000, ModelPrices(5.0, 6.25, 0.5, 25.0), "Opus 4.7"),
    "claude-opus-4-6": ModelFacts(1_000_000, ModelPrices(5.0, 6.25, 0.5, 25.0), "Opus 4.6"),
    "claude-sonnet-5-5": ModelFacts(1_000_000, ModelPrices(2.0, 2.5, 0.2, 10.0), "Sonnet 5.5"),
    "claude-sonnet-5": ModelFacts(1_000_000, ModelPrices(2.0, 2.5, 0.2, 10.0), "Sonnet 5"),
    "claude-sonnet-4-6": ModelFacts(1_000_000, ModelPrices(3.0, 3.75, 0.3, 15.0), "Sonnet 4.6"),
    "claude-haiku-4-5": ModelFacts(200_000, ModelPrices(1.0, 1.25, 0.1, 5.0), "Haiku 4.5"),
    "gpt-6-astra": ModelFacts(None, ModelPrices(10.0, 12.5, 1.0, 50.0), "GPT-6 Astra"),
    "gpt-6-sol": ModelFacts(None, ModelPrices(2.0, 2.5, 0.2, 10.0), "GPT-6 Sol"),
    "gpt-6-luna": ModelFacts(None, ModelPrices(0.1, 0.125, 0.01, 0.5), "GPT-6 Luna"),
    "gpt-5.6-sol": ModelFacts(None, ModelPrices(4.0, 5.0, 0.4, 20.0), "GPT-5.6 Sol"),
    "gpt-5-codex": ModelFacts(400_000, ModelPrices(1.25, 0.0, 0.125, 10.0), "GPT-5 Codex"),
    "gpt-5-mini": ModelFacts(400_000, ModelPrices(0.25, 0.0, 0.025, 2.0), "GPT-5 mini"),
    "gpt-5-nano": ModelFacts(400_000, ModelPrices(0.05, 0.0, 0.005, 0.4), "GPT-5 nano"),
    "gpt-5": ModelFacts(400_000, ModelPrices(1.25, 0.0, 0.125, 10.0), "GPT-5"),
}


def facts_for_model(model: Optional[str]) -> Optional[ModelFacts]:
    if not model:
        return None
    text = str(model)
    if text in MODEL_TABLE:
        return MODEL_TABLE[text]
    base = re.sub(r"-(?:[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})$", "", text)
    return MODEL_TABLE.get(base)



def estimate_cost_usd(
    model: Optional[str],
    *,
    input_tokens: int,
    cache_creation_input_tokens: int,
    cache_read_input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    facts = facts_for_model(model)
    if facts is None or facts.prices is None:
        return None
    p = facts.prices
    dollars = (
        input_tokens * p.input
        + cache_creation_input_tokens * p.cache_write
        + cache_read_input_tokens * p.cache_read
        + output_tokens * p.output
    ) / 1_000_000.0
    return round(dollars, 4)


def window_for_model(model: Optional[str]) -> Optional[int]:
    facts = facts_for_model(model)
    return facts.window_tokens if facts is not None else None


COST_TIER_THRESHOLDS = (2.0, 8.0, 16.0, 32.0)


def cost_tier_for_model(model: Optional[str]) -> Optional[int]:
    facts = facts_for_model(model)
    if facts is None or facts.prices is None:
        return None
    output = facts.prices.output
    for step, boundary in enumerate(COST_TIER_THRESHOLDS, start=1):
        if output < boundary:
            return step
    return len(COST_TIER_THRESHOLDS) + 1


def display_name_for_model(model: Optional[str]) -> Optional[str]:
    facts = facts_for_model(model)
    return facts.display_name if facts is not None else None


_DROPPED_PREFIX = "claude-"
_CAPITAL_WORD = "gpt"


def readable_model_name(model: Optional[str]) -> str:
    known = display_name_for_model(model)
    if known:
        return known
    text = str(model or "").strip()
    if not text:
        return ""
    text = re.sub(r"-(?:[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})$", "", text)
    if text.lower().startswith(_DROPPED_PREFIX) and len(text) > len(_DROPPED_PREFIX):
        text = text[len(_DROPPED_PREFIX):]
    text = re.sub(r"(?<=\d)-(?=\d)", ".", text)
    parts = [part for part in re.split(r"[-_\s]+", text) if part]
    words = [part.upper() if part.lower() == _CAPITAL_WORD else part[:1].upper() + part[1:] for part in parts]
    if len(words) > 1 and words[0] == _CAPITAL_WORD.upper() and words[1][:1].isdigit():
        words[:2] = [f"{words[0]}-{words[1]}"]
    return " ".join(words)
