
from __future__ import annotations

from contextlib import closing
from types import SimpleNamespace
from typing import Dict

import pytest

from src.core.db import connect, db_path_for
from src.core.inventory.model import DELETE, ROLE_SECRET, SCOPE_PROJECT, Inventory
from src.core.inventory.resolve import resolve_project, resolve_project_target, resolve_session, resolve_session_target
from src.core.inventory.target import TargetNotFound
from src.core.inventory.model import ProjectNotFound
from src.core.session_purge.plan import build_plan
from tests.python.inventory.world import (A, APP_A, B, CONV_A, CONV_A0, CONV_B, P, UUID_A, UUID_B)


@pytest.fixture(scope="module")
def inv(seeded: SimpleNamespace) -> Dict[str, Inventory]:
    with closing(connect(db_path_for(seeded.state))) as conn:
        return {A: resolve_session(conn, UUID_A, seeded.locations), B: resolve_session(conn, UUID_B, seeded.locations),
                P: resolve_project(conn, seeded.p1, seeded.locations)}


def test_every_rows_artifact_can_be_found_again(inv: Dict[str, Inventory]) -> None:
    for subject, answer in inv.items():
        for art in answer.artifacts:
            if art.kind == "rows":
                assert art.locator, f"{subject}: {art.store}.{art.what} has no locator"


def test_every_artifact_names_its_store(inv: Dict[str, Inventory]) -> None:
    for answer in inv.values():
        assert all(a.store for a in answer.all_artifacts())


def test_the_session_row_names_the_fields_an_export_rewrites(inv: Dict[str, Inventory]) -> None:
    row = next(a for a in inv[A].artifacts if a.store == "cloude.db" and a.table == "sessions")
    names = {f.name for f in row.rewrite}
    assert {"id", "session_uuid", "project_id"} <= names


def test_a_share_link_secret_is_marked_secret(inv: Dict[str, Inventory]) -> None:
    links = [a for a in inv[A].artifacts if a.table == "spectator_links"]
    assert links, "spectator_links not listed"
    secret = {f.name for a in links for f in a.rewrite if f.role == ROLE_SECRET}
    assert {"token_sha256", "link_nonce"} <= secret


def test_session_a_lists_the_conversation_it_ran_before(inv: Dict[str, Inventory]) -> None:
    assert set(inv[A].conversations) >= {CONV_A, CONV_A0}


def test_a_target_resolves_by_row_id_app_id_and_either_conversation(seeded: SimpleNamespace, conn) -> None:
    for target in (f"row:{seeded.row_a}", APP_A, UUID_A, CONV_A, CONV_A0):
        assert resolve_session_target(conn, target, seeded.locations).session.session_uuid == UUID_A, target
    assert resolve_session_target(conn, CONV_B, seeded.locations).session.session_uuid == UUID_B


def test_an_unknown_target_is_refused(seeded: SimpleNamespace, conn) -> None:
    with pytest.raises(TargetNotFound):
        resolve_session_target(conn, "nothing-like-this", seeded.locations)
    with pytest.raises(ProjectNotFound):
        resolve_project_target(conn, "no such project", seeded.locations)


def test_a_project_resolves_by_id_uid_folder_and_name(seeded: SimpleNamespace, conn) -> None:
    for target in (str(seeded.p1), "project-uid-1", seeded.root1, "Proj One"):
        found = resolve_project_target(conn, target, seeded.locations)
        assert found.scope == SCOPE_PROJECT and found.project.project_id == seeded.p1, target


def test_the_purge_plan_is_the_resolvers_answer_and_deletes_nothing_new(seeded: SimpleNamespace, conn, inv: Dict[str, Inventory]) -> None:
    plan = build_plan(conn, UUID_A, state_dir=seeded.state, config_path=seeded.config, panes=(True, []),
                      homes=[seeded.home], codex=seeded.codex)
    assert [a.material() for a in plan.artifacts] == [a.material() for a in inv[A].artifacts]
    deleted = {(a.store, a.table) for a in plan.artifacts if a.action == DELETE and a.kind == "rows"}
    assert deleted <= {(store, table) for (tag, store, table) in seeded.ledger.rows if tag == A}
    for art in plan.artifacts:
        if art.store == "cloude.db" and art.table in {"lineage_edges", "crosstalk_messages", "project_storage"}:
            assert art.action != DELETE, f"{art.table} is newly covered and must only be reported"
