
from __future__ import annotations

import asyncio
from contextlib import closing

import pytest

from tests.python.swarm.test_swarm_turn_on_fixes import BASE, _agent, world  # noqa: F401
from src.core.crosstalk import directory
from src.core.db import connect, db_path_for
from src.core.swarm import naming_rules, project_agent, rename, spawn, store

ARGS = {"job": "repaint the nodes", "goal": "do it", "task_type": "nodes", "rank": "task"}


def _db(world, fn):
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        return fn(conn)


def test_spawn_refuses_a_long_or_prefixed_name_and_honors_a_good_one(world):  # noqa: F811
    parent = _agent(world)
    for bad, needle in (("Fold The Changes Rail Into The File Browser", "the limit is 25"), ("feat: file changes", "starts with 'feat'"),
                        ("Fix org chart labels", "starts with 'Fix'"), ("TWEAK-colors", "starts with 'TWEAK'")):
        with pytest.raises(spawn.SpawnRefused, match=needle) as refused:
            asyncio.run(spawn.prepare_for(parent, {**ARGS, "name": bad}))
        assert "fixing node colors" in str(refused.value) and "Icon Design" in str(refused.value)
    assert asyncio.run(spawn.prepare_for(parent, {**ARGS, "name": "Fixing Node Colors"})).request["display_name"] == "Fixing Node Colors"
    assert asyncio.run(spawn.prepare_for(parent, ARGS)).request["display_name"] == "repaint the nodes"
    with pytest.raises(spawn.SpawnRefused, match="name is required"):
        asyncio.run(spawn.prepare_for(parent, {**ARGS, "job": "fix: the org chart leaf labels run past the edge"}))
    with pytest.raises(spawn.SpawnRefused, match="specialty is required"):
        asyncio.run(spawn.prepare_for(parent, {**ARGS, "rank": "feature"}))
    plan = asyncio.run(spawn.prepare_for(parent, {**ARGS, "rank": "feature", "specialty": "Icon Design"}))
    assert plan.request["display_name"] == "Icon Design" and plan.request["specialty"] == "Icon Design"


def test_a_duplicate_specialty_is_redirected_to_the_live_specialist(world):  # noqa: F811
    parent = _agent(world)
    icon = _db(world, lambda c: store.create_agent(c, slug="icon-design", rank="feature", job="icons", display_name="Icon Design",
                                                   repo_dir=parent["repo_dir"], effort="medium", parent_id=parent["id"], specialty="Icon Design"))
    for args in ({**ARGS, "rank": "feature", "specialty": "icon design"}, {**ARGS, "name": "Icon-Design"}):
        with pytest.raises(spawn.SpawnRedirect) as redirected:
            asyncio.run(spawn.prepare_for(parent, args))
        answer = redirected.value.answer()
        assert answer["spawned"] is False and answer["suggested_agent"]["agent_id"] == icon["id"]
    plan = asyncio.run(spawn.prepare_for(parent, {**ARGS, "rank": "feature", "specialty": "Icon Design", "spawn_reason": "a second icon set"}))
    assert plan.request["specialty"] == "Icon Design"


def test_rename_works_after_naming_approval_keeps_the_old_name_and_refuses_a_duplicate(world):  # noqa: F811
    world.cfg.write_text('{"swarm": {"naming_family": true}}')
    item = asyncio.run(world.port.post_card(world.boss["thread_key"], "waiting", "naming family", "x", f"naming:{world.boss['id']}"))
    world.client.patch(f"{BASE}/items/{item}", json={"approved": True})
    approved = _agent(world)
    assert approved["naming_state"] == "approved" and approved["display_name"] == "Etna"

    renamed = asyncio.run(rename.rename(approved["id"], "HE.LI.OS. (Home)"))
    assert renamed["display_name"] == "HE.LI.OS. (Home)" and renamed["slug"] == approved["slug"] and renamed["thread_key"] == approved["thread_key"]
    assert naming_rules.former_names(renamed) == ["Etna"]
    assert _db(world, lambda c: c.execute("SELECT title FROM sessions WHERE id = ?", (world.row_id,)).fetchone()[0]) == "HE.LI.OS. (Home)"
    card = {"name": "HE.LI.OS. (Home)", "id": "ses_x", "tmux_name": "cloude_p", "former_names": naming_rules.former_names(renamed)}
    assert directory.resolve_handle("@Etna", [card]).tier == "label"

    _db(world, lambda c: store.create_agent(c, slug="style-guide", rank="feature", job="style", display_name="Style Guide",
                                            repo_dir=approved["repo_dir"], effort="medium", parent_id=approved["id"]))
    with pytest.raises(rename.RenameRefused, match="already holds"):
        asyncio.run(rename.rename(approved["id"], "style guide"))
    for bad in ("", "fix the guide", "x" * 26):
        with pytest.raises(rename.RenameRefused):
            asyncio.run(rename.rename(approved["id"], bad))


def test_naming_family_off_posts_no_card_and_turn_on_asks_for_none(world):  # noqa: F811
    assert '"naming_family"' not in world.cfg.read_text()
    before = world.client.get(f"{BASE}/lists/{world.boss['thread_key']}").json()["items"]
    with pytest.raises(project_agent.TurnOnError, match="naming family is off"):
        asyncio.run(project_agent.propose_naming(_agent(world), "Norse gods", "Odin", "short names"))
    assert world.client.get(f"{BASE}/lists/{world.boss['thread_key']}").json()["items"] == before
    assert "naming family" not in project_agent.PLAIN_ORDERS
