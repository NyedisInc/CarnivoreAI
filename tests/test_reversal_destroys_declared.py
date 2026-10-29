
from __future__ import annotations

import re

from src.core import db_models

NAME = re.compile(r"^REVERSAL_SQL_V(\d+)$")

AT_LEAST = 5


def _reversals() -> dict:
    found = {}
    for name in dir(db_models):
        match = NAME.match(name)
        if not match:
            continue
        found[int(match.group(1))] = getattr(db_models, name)
    return found


def test_the_scan_actually_found_the_reversals() -> None:
    reversals = _reversals()
    assert len(reversals) >= 10
    non_empty = {version for version, sql in reversals.items() if sql}
    assert len(non_empty) >= AT_LEAST, non_empty
    assert 8 in non_empty
    assert 24 in non_empty


def test_every_reversible_step_names_what_it_destroys() -> None:
    undeclared = sorted(
        version
        for version, sql in _reversals().items()
        if sql and version not in db_models.REVERSAL_DESTROYS
    )
    assert undeclared == [], (
        "these schema versions can be reversed but do not say what that "
        f"destroys: {undeclared}"
    )


def test_an_empty_reversal_is_exempt() -> None:
    empty = [version for version, sql in _reversals().items() if not sql]
    assert empty, "no additive-only step found, so the exemption is untested"
    assert 4 in empty
    assert 4 not in db_models.REVERSAL_DESTROYS


def test_an_empty_declaration_is_still_a_declaration() -> None:
    assert db_models.REVERSAL_SQL_V7
    assert 7 in db_models.REVERSAL_DESTROYS
    assert db_models.REVERSAL_DESTROYS[7] == ()


def test_the_v30_note_table_declares_its_loss() -> None:
    assert db_models.REVERSAL_SQL_V30
    assert "session_notes" in db_models.REVERSAL_SQL_V30[0]
    assert db_models.REVERSAL_DESTROYS[30] == ("session_notes (whole table)",)


def test_no_declaration_names_a_version_this_schema_has_never_had() -> None:
    unknown = sorted(
        version
        for version in db_models.REVERSAL_DESTROYS
        if version < 1 or version > db_models.CURRENT_SCHEMA_VERSION
    )
    assert unknown == []
