
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transcript_contract"


def load(family: str) -> List[Dict[str, str]]:
    doc = json.loads((FIXTURES / f"{family}_lines.json").read_text(encoding="utf-8"))
    assert doc["synthetic"] is True
    return doc["lines"]
