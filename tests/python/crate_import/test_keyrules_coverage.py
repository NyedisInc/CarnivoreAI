
from __future__ import annotations

from typing import Dict, List

from src.core.crate_import import keyrules, policy
from src.core.inventory import registry
from src.core.inventory.claims import ClaimBook


def missing_rules(book: ClaimBook, rules: Dict[str, Dict[str, keyrules.KeyRule]]) -> List[str]:
    missing: List[str] = []
    for claim in book.claims:
        decision = policy.decision_for(book, claim.store, claim.table)
        if claim.derived or decision is None or not decision.writes:
            continue
        for key in claim.keys:
            if key not in rules.get(f"{claim.store}.{claim.table}", {}):
                missing.append(f"{claim.store}.{claim.table}.{key}")
    return sorted(set(missing))


def test_every_written_key_has_a_rule() -> None:
    assert missing_rules(registry.book(), keyrules.RULES) == []


def test_every_rule_names_a_real_table_and_a_known_kind() -> None:
    book = registry.book()
    for table, keys in keyrules.RULES.items():
        store, name = table.rsplit(".", 1)
        assert book.claims_for(store, name), f"a rule for {table}, which no claim names"
        for key, rule in keys.items():
            assert rule.kind in keyrules.KINDS, (table, key)
            assert (rule.kind == keyrules.REF) == bool(rule.target), (table, key)


def test_the_check_goes_red_on_a_removed_rule() -> None:
    book = registry.book()
    trimmed = {t: dict(k) for t, k in keyrules.RULES.items()}
    del trimmed["cloude.db.sessions"]["tmux_name"]
    assert missing_rules(book, trimmed) == ["cloude.db.sessions.tmux_name"]
    assert keyrules.rule_for("cloude.db", "sessions", "no_such_key") is None
