
from __future__ import annotations

from scripts.schema_ledger.ladders import LADDERS
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.schema_ledger.ledger import check_ledger, parse_ledger


def test_core_ledger_matches_code() -> None:
    check_ledger(LADDERS["core"])


def test_core_ledger_covers_every_schema_version() -> None:
    assert len(parse_ledger(LADDERS["core"].path, "C")) == CURRENT_SCHEMA_VERSION
