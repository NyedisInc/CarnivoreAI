
from __future__ import annotations

from typing import Dict, Optional

from src.cplugs.huddle import rules

FIELD = "perceived_ask"
MAX_PERCEIVED_ASK = 300


def clean_fields(value: Optional[object]) -> Dict[str, Optional[str]]:
    if value is None:
        return {}
    text = " ".join(rules.clean_text(value, FIELD, MAX_PERCEIVED_ASK, allow_blank=True).split())
    return {FIELD: text or None}
