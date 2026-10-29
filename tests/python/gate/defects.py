
from __future__ import annotations

from typing import Tuple

import pytest

from scripts.gate.known_defects import KNOWN


def xfail_for(key: str) -> pytest.MarkDecorator:
    issue, why = KNOWN[key]
    return pytest.mark.xfail(strict=True, reason=f"#{issue}: {why}")


def known(key: str) -> Tuple[int, str]:
    return KNOWN[key]
