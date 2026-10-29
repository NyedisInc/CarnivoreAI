
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.schema_ledger.errors import FreezeViolation, LedgerFormatError, LedgerMismatch
from src.core.schema_ledger.freeze import check_freeze, read_freeze
from src.core.schema_ledger.hashing import normalized_source, sql_rung_hash, step_rung_hash
from src.core.schema_ledger.ledger import (
    LadderSpec, append_missing, check_ledger, parse_ledger, sql_rungs, slugify,
)

SCRIPTS = ["CREATE TABLE a (x INTEGER);", "ALTER TABLE a ADD COLUMN y TEXT;"]


def _spec(tmp_path: Path, scripts: list[str]) -> LadderSpec:
    return LadderSpec("t", "T", tmp_path / "t.ledger", lambda: sql_rungs(scripts))


def test_append_then_check_passes(tmp_path: Path) -> None:
    spec = _spec(tmp_path, SCRIPTS)
    assert len(append_missing(spec, "joe")) == 2
    check_ledger(spec)
    assert parse_ledger(spec.path, "T")[1].author == "joe"


def test_changed_rung_goes_red_and_names_both_hashes(tmp_path: Path) -> None:
    append_missing(_spec(tmp_path, SCRIPTS), "-")
    changed = _spec(tmp_path, [SCRIPTS[0], SCRIPTS[1] + " "])
    with pytest.raises(LedgerMismatch) as err:
        check_ledger(changed)
    assert "T2" in str(err.value) and sql_rung_hash(SCRIPTS[1])[:12] in str(err.value)
    with pytest.raises(LedgerMismatch):
        append_missing(changed, "-")


def test_new_rung_without_a_line_goes_red_and_extra_line_goes_red(tmp_path: Path) -> None:
    append_missing(_spec(tmp_path, SCRIPTS), "-")
    with pytest.raises(LedgerMismatch, match="has no line"):
        check_ledger(_spec(tmp_path, SCRIPTS + ["CREATE TABLE b (z);"]))
    with pytest.raises(LedgerMismatch, match="no such rung"):
        check_ledger(_spec(tmp_path, SCRIPTS[:1]))


@pytest.mark.parametrize("body", ["T2 " + "a" * 64 + " - x\n", "T1 nothex - x\n", "X1 " + "a" * 64 + " - x\n"])
def test_malformed_ledgers_are_refused(tmp_path: Path, body: str) -> None:
    path = tmp_path / "t.ledger"
    path.write_text(body)
    with pytest.raises(LedgerFormatError):
        parse_ledger(path, "T")


def test_missing_ledger_is_a_format_error_not_a_pass(tmp_path: Path) -> None:
    with pytest.raises(LedgerFormatError):
        check_ledger(_spec(tmp_path, SCRIPTS))


def test_step_hash_ignores_comments_and_blank_lines_but_sees_code_and_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    assert normalized_source("  a = 1  \n\n  # c\n  b = 2\n") == "a = 1\nb = 2"
    from src.core import db_steps

    step = db_steps.STEPS[18]
    before = step_rung_hash(step)
    assert before == step_rung_hash(step)
    monkeypatch.setattr(db_steps, "DDL_V19", (*db_steps.DDL_V19, "-- changed"))
    assert step_rung_hash(step) != before


def test_step_hash_follows_a_ddl_helper() -> None:
    from src.core import db_steps

    assert step_rung_hash(db_steps.STEPS[91]) != step_rung_hash(db_steps.STEPS[90])


def test_slugify() -> None:
    assert slugify("Messaging: unconfirmed (table rebuild)") == "messaging-unconfirmed-table-rebuild"
    assert slugify("???") == "rung"


def test_freeze_fails_on_a_new_rung_and_a_lost_rung(tmp_path: Path) -> None:
    marker = tmp_path / "x.freeze"
    marker.write_text("# c\nfrozen_rungs 3\n")
    check_freeze("x", marker, 3, "the plan")
    for count in (4, 2):
        with pytest.raises(FreezeViolation, match="the plan"):
            check_freeze("x", marker, count, "the plan")
    marker.write_text("nothing here\n")
    with pytest.raises(LedgerFormatError):
        read_freeze(marker)
