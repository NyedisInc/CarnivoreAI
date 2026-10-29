
from __future__ import annotations

from contextlib import closing
from types import SimpleNamespace

import pytest

from src.core.db import connect, db_path_for
from src.core.inventory.resolve import resolve_project_target, resolve_session, resolve_session_target
from tests.python.inventory.world_build import build_world
from tests.python.inventory.world import CONV_A0, UUID_A


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> SimpleNamespace:
    w = build_world(tmp_path_factory.mktemp("related"))
    outside = w.tmp / "elsewhere"
    outside.mkdir()
    (outside / f"{CONV_A0}.jsonl").write_text("{}\n")
    (w.home / "projects" / "-linked-folder").symlink_to(outside)
    return w


def test_default_drops_and_a_list_collects(world: SimpleNamespace) -> None:
    with closing(connect(db_path_for(world.state))) as conn:
        plain = resolve_session(conn, UUID_A, world.locations)
        collected: list = []
        carried = resolve_session(conn, UUID_A, world.locations, related_blockers=collected)
    assert not any(CONV_A0 in b for b in plain.blockers)
    assert plain.blockers == carried.blockers
    assert len(collected) == 1 and CONV_A0 in collected[0] and "outside" in collected[0]


def test_targets_and_projects_pass_the_list_through(world: SimpleNamespace) -> None:
    with closing(connect(db_path_for(world.state))) as conn:
        by_target: list = []
        resolve_session_target(conn, UUID_A, world.locations, related_blockers=by_target)
        by_project: list = []
        resolve_project_target(conn, str(world.p1), world.locations, related_blockers=by_project)
    assert len(by_target) == 1 and len(by_project) == 1
