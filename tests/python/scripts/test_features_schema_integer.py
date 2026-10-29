
from __future__ import annotations

from scripts.features_schema import CHANGE_FIELDS, validate_record

BASE = {"date": "2026-10-27", "type": "fix", "features": ["x"], "summary": "s", "title": "t"}


def _errors(**extra) -> list[str]:
    return [e for e in validate_record({**BASE, **extra}, CHANGE_FIELDS, "w") if "'pr'" in e or "'issue'" in e]


def test_a_string_pr_is_rejected() -> None:
    assert _errors(pr="not-a-number")


def test_a_boolean_issue_is_rejected() -> None:
    assert _errors(issue=True)


def test_real_integers_pass() -> None:
    assert _errors(pr=12, issue=3) == []
def test_null_means_none() -> None:
    assert _errors(pr=None, issue=None) == []
