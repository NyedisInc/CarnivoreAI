
from __future__ import annotations

from contextlib import closing

from src.core.db import connect
from src.core.project_move.apply import apply_plan
from src.core.swarm import store
from tests.python.projects.move_world import plan_for


def _agent(conn, slug: str, repo_dir: str, project_id: int) -> int:
    return store.create_agent(conn, slug=slug, rank="project", job="j", display_name=slug, repo_dir=repo_dir, effort="high",
                              project_id=project_id)["id"]


def test_a_move_rebases_the_repo_dir_of_the_projects_agents_and_leaves_others(world):
    with closing(connect(world.db, create=False)) as conn:
        root = _agent(conn, "alpha-agent", str(world.old), world.ids["alpha"])
        child = _agent(conn, "sub-agent", str(world.sub), world.ids["sub"])
        sibling = _agent(conn, "x-agent", str(world.sibling), world.ids["alpha_x"])
    plan = plan_for(world, move_folder=True)
    assert plan.ok, plan.failed()
    with closing(connect(world.db, create=False)) as conn:
        done = apply_plan(conn, plan, state_dir=world.state)
        dirs = {r[0]: r[1] for r in conn.execute("SELECT id, repo_dir FROM swarm_agents")}
    assert done["swarm_agents"] == 2
    assert dirs == {root: str(world.new), child: str(world.new / "sub"), sibling: str(world.sibling)}
