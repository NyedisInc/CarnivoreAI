
from __future__ import annotations

from typing import Dict, List

from src.core.crate_import import policy
from src.core.inventory import registry
from src.core.inventory.claims import ClaimBook


def audit(book: ClaimBook, decisions: Dict[str, policy.Decision]) -> List[str]:
    problems: List[str] = []
    named = {f"{c.store}.{c.table}" for c in book.claims} | {f"{e.store}.{e.table}" for e in book.exclusions}
    for claim in book.claims:
        key = f"{claim.store}.{claim.table}"
        got = decisions.get(key)
        if got is None and not all(c.derived for c in book.claims_for(claim.store, claim.table)):
            problems.append(f"{key} is claimed and not derived, with no decision")
        if got is not None and got.kind == policy.DERIVED and not all(c.derived for c in book.claims_for(claim.store, claim.table)):
            problems.append(f"{key} is marked derived but a claim of it is not derived")
    for key in decisions:
        if key not in named:
            problems.append(f"{key} has a decision and no claim or exclusion")
    return problems


def test_the_policy_table_matches_the_registry() -> None:
    assert audit(registry.book(), policy.DECISIONS) == []


def test_decision_for_answers_every_claimed_table_and_not_an_unknown_one() -> None:
    book = registry.book()
    for claim in book.claims:
        assert policy.decision_for(book, claim.store, claim.table) is not None, (claim.store, claim.table)
    assert policy.decision_for(book, "cloude.db", "a_table_from_a_newer_build") is None
    assert policy.decision_for(book, "stats.db", "stats_annotations").kind == policy.RESTORE


def test_the_check_goes_red_on_a_removed_decision() -> None:
    trimmed = {k: v for k, v in policy.DECISIONS.items() if k != "cloude.db.sessions"}
    assert any("cloude.db.sessions" in p for p in audit(registry.book(), trimmed))


def test_the_check_goes_red_on_a_non_derived_claim_marked_derived() -> None:
    wrong = {**policy.DECISIONS, "stats.db.stats_annotations": policy.Decision(policy.DERIVED)}
    assert any("stats_annotations" in p for p in audit(registry.book(), wrong))
