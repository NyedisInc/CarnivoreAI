
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from src.core.session_token_usage.model_table import MODEL_TABLE, facts_for_model

RATES = {name: None if facts.prices is None else {
    "input": facts.prices.input, "cache_write": facts.prices.cache_write,
    "cache_read": facts.prices.cache_read, "output": facts.prices.output,
} for name, facts in MODEL_TABLE.items()}
RATES_JSON = json.dumps(RATES, sort_keys=True, separators=(",", ":"))
PRICE_VERSION = "model-table-" + hashlib.sha256(RATES_JSON.encode()).hexdigest()[:16]
PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing; https://platform.claude.com/docs/en/about-claude/pricing; standard short-context API-equivalent rates"
PRICE_SOURCE_DATE = "2026-09-29"


def estimate(model: str, counts: tuple[int, int, int, int]) -> tuple[int | None, str | None]:
    facts = facts_for_model(model)
    if facts is None or facts.prices is None:
        return None, None
    cost = sum(Decimal(str(getattr(facts.prices, key))) * count for key, count in zip(
        ("input", "cache_write", "cache_read", "output"), counts
    )) * Decimal(1000)
    return int(cost.quantize(Decimal("1"), rounding=ROUND_HALF_UP)), PRICE_VERSION
