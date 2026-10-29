
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Optional, Tuple

from src.core.message_model_secrets import DETECTOR_BEARER_TOKEN, DETECTOR_JWT, EXTRA_VENDOR_DETECTORS, VENDOR_DETECTORS, scan_text
from src.core.secret_scanning.deadline import Deadline, ScanTimeout  # noqa: F401

FILE_DETECTORS: Tuple[str, ...] = VENDOR_DETECTORS + EXTRA_VENDOR_DETECTORS + (DETECTOR_BEARER_TOKEN, DETECTOR_JWT)


_COMPLETE_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+){2}|eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*(?:\.[A-Za-z0-9_\-]+){3}")
_NAME_PIECE = re.compile(r"[A-Za-z]+[0-9]{0,2}")
_SEPARATORS = re.compile(r"[\-_.~+/]")


def _is_real_bearer(value: str) -> bool:
    token = value.rstrip("=")
    if token.startswith("eyJ"):
        return _COMPLETE_JWT.fullmatch(token) is not None
    if not any(c.isdigit() for c in token):
        return False
    return not all(_NAME_PIECE.fullmatch(piece) for piece in _SEPARATORS.split(token) if piece)


def credential_counts(text: str, deadline: Optional[Deadline] = None) -> Dict[str, int]:
    names: Counter = Counter()
    for f in scan_text(text, FILE_DETECTORS, deadline=deadline):
        if f.detector != DETECTOR_BEARER_TOKEN:
            names[f.detector] += 1
            continue
        value = text[f.offset:f.offset + f.length]
        if scan_text(value, (DETECTOR_JWT,)):
            names[DETECTOR_JWT] += 1
        elif _is_real_bearer(value):
            names[DETECTOR_BEARER_TOKEN] += 1
    return dict(names)
