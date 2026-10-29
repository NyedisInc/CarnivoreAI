
from __future__ import annotations

from typing import Dict, Tuple

REPORT_FIELDS: Tuple[str, ...] = ("item_id", "version", "account_id")

GUEST_FIELDS: Tuple[str, ...] = (
    "public_key", "install_id", "terms_version", "age_attested", "client", "label", "ts", "pow", "signature",
)

FIELD_KEY_PREFIX = "privacy.install_report.field."


def disclosure() -> Dict[str, Tuple[str, ...]]:
    return {"report": REPORT_FIELDS, "guest": GUEST_FIELDS}


def field_key(field_id: str) -> str:
    return FIELD_KEY_PREFIX + field_id
