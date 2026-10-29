
from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from typing import Dict, Tuple

import pytest

from src.core.inventory import registry
from src.core.inventory.model import SCOPE_PROJECT, SCOPE_SESSION, Inventory
from src.core.inventory.resolve import resolve_project, resolve_session
from tests.python.inventory.world import A, B, P, UUID_A, UUID_B

FILE_KINDS = ("file", "dir")


def rows_listed(inv: Inventory) -> Dict[Tuple[str, str], int]:
    out: Counter = Counter()
    for art in inv.artifacts:
        if art.kind == "rows":
            out[(art.store, art.table)] += art.count
    return dict(out)


def files_listed(inv: Inventory) -> Dict[Tuple[str, str], int]:
    return {(a.store, a.what): 1 for a in inv.artifacts if a.kind in FILE_KINDS}


def seeded_rows(w: SimpleNamespace, subject: str) -> Dict[Tuple[str, str], int]:
    return {(store, table): n for (tag, store, table), n in w.ledger.rows.items() if tag == subject}


def seeded_files(w: SimpleNamespace, subject: str) -> Dict[Tuple[str, str], int]:
    return {(store, path): n for (tag, store, path), n in w.ledger.files.items() if tag == subject}


@pytest.fixture(scope="module")
def answers(seeded: SimpleNamespace) -> Dict[str, Inventory]:
    from contextlib import closing

    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(seeded.state))) as conn:
        return {A: resolve_session(conn, UUID_A, seeded.locations), B: resolve_session(conn, UUID_B, seeded.locations),
                P: resolve_project(conn, seeded.p1, seeded.locations)}


@pytest.mark.parametrize("subject", [A, B, P])
def test_the_resolver_lists_every_seeded_row_and_nothing_else(seeded: SimpleNamespace, answers: Dict[str, Inventory], subject: str) -> None:
    got, want = rows_listed(answers[subject]), seeded_rows(seeded, subject)
    assert not [k for k in want if k not in got], f"seeded but not listed: {sorted(k for k in want if k not in got)}"
    assert not [k for k in got if k not in want], f"listed but never seeded for {subject} (a decoy leaked, or a claim has no seed): {sorted(k for k in got if k not in want)}"
    assert {k: v for k, v in got.items() if got[k] != want[k]} == {}, {k: (got[k], want[k]) for k in got if got[k] != want[k]}


@pytest.mark.parametrize("subject", [A, B, P])
def test_the_resolver_lists_every_seeded_file_and_nothing_else(seeded: SimpleNamespace, answers: Dict[str, Inventory], subject: str) -> None:
    got, want = files_listed(answers[subject]), seeded_files(seeded, subject)
    assert sorted(k for k in want if k not in got) == [], "seeded but not listed"
    assert sorted(k for k in got if k not in want) == [], "listed but never seeded (a decoy leaked)"


def entries_listed(inv: Dict[str, Inventory] | Inventory) -> Dict[Tuple[str, str], int]:
    return {(a.store, a.what): 1 for a in inv.artifacts if a.kind == "entry"}


def seeded_entries(w: SimpleNamespace, subject: str) -> Dict[Tuple[str, str], int]:
    return {(store, what): n for (tag, store, what), n in w.ledger.entries.items() if tag == subject}


@pytest.mark.parametrize("subject", [A, B, P])
def test_the_resolver_lists_every_seeded_json_entry_and_nothing_else(seeded: SimpleNamespace, answers: Dict[str, Inventory], subject: str) -> None:
    got, want = entries_listed(answers[subject]), seeded_entries(seeded, subject)
    assert sorted(k for k in want if k not in got) == [], "seeded but not listed"
    assert sorted(k for k in got if k not in want) == [], "listed but never seeded (a decoy leaked, or a phantom entry)"


def test_a_pinned_theme_is_matched_on_the_key_never_a_substring(seeded: SimpleNamespace, answers: Dict[str, Inventory]) -> None:
    assert [a for a in answers[B].artifacts if a.store == "pinned_themes.json"] == []
    assert [a.what for a in answers[A].artifacts if a.store == "pinned_themes.json"] == [seeded_tmux(seeded, A)]


def seeded_tmux(w: SimpleNamespace, subject: str) -> str:
    from tests.python.inventory.world import TMUX_A, TMUX_B

    return {A: TMUX_A, B: TMUX_B}[subject]


def test_codex_lines_and_snapshots_name_only_the_thread(seeded: SimpleNamespace, answers: Dict[str, Inventory]) -> None:
    from tests.python.inventory.world import CONV_A

    lines = [a for a in answers[A].artifacts if a.kind == "lines" and a.store == "codex"]
    assert [(a.count, a.action) for a in lines] == [(1, "report")] and lines[0].locator["match"] == CONV_A
    snapshots = [a for a in answers[A].artifacts if a.store == "codex" and "shell_snapshots" in a.what]
    assert [a.action for a in snapshots] == ["report"]
    assert [a for a in answers[B].artifacts if a.store == "codex"] == []


def test_every_claim_is_exercised_by_a_seed(seeded: SimpleNamespace) -> None:
    subjects = {SCOPE_SESSION: (A, B), SCOPE_PROJECT: (P,)}
    untried = []
    for claim in registry.book().claims:
        if claim.covered_by:
            continue
        for scope in claim.scopes:
            if not any(seeded.ledger.rows.get((s, claim.store, claim.table)) for s in subjects[scope]):
                untried.append(f"{claim.store}.{claim.table} ({scope})")
    assert untried == []


def test_a_project_answers_with_one_inventory_per_session_row(seeded: SimpleNamespace, answers: Dict[str, Inventory]) -> None:
    project = answers[P]
    assert project.scope == SCOPE_PROJECT and project.project.project_id == seeded.p1
    assert [c.session.session_uuid for c in project.children] == [UUID_A, UUID_B]
    assert all(c.scope == SCOPE_SESSION for c in project.children)
    assert project.outside == []


def test_an_unreadable_table_is_reported_not_swallowed(answers: Dict[str, Inventory]) -> None:
    for inv in (answers[A], answers[B], answers[P]):
        assert [a for a in inv.all_artifacts() if "could not be" in a.reason] == []
        assert inv.blockers == []
