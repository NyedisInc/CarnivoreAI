
from __future__ import annotations

from contextlib import closing

from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.swarm import leaders, store, views
from src.core.swarm.names import shown_name


def test_leaders_show_without_agent_and_store_keeps_it(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, CURRENT_SCHEMA_VERSION)
        made = {name: store.create_agent(conn, slug=slug, rank=rank, job="j", display_name=name, repo_dir="/tmp/swarm-x", effort="high")
                for slug, rank, name in (("sysop", "alpha", "SysOp"), ("acme", "company", "Acme agent"),
                                         ("carnivore", "project", "Carnivore.ai agent"), ("loki", "feature", "Loki agent"),
                                         ("etna", "task", "Etna agent"))}
        shown = {name: views.summarize(store.get_agent(conn, a["id"]), {})["display_name"] for name, a in made.items()}
        assert shown == {"SysOp": "SysOp", "Acme agent": "Acme", "Carnivore.ai agent": "Carnivore.ai",
                         "Loki agent": "Loki agent", "Etna agent": "Etna agent"}
        assert [store.get_agent(conn, a["id"])["display_name"] for a in made.values()] == list(made)
        company = store.get_agent(conn, made["Acme agent"]["id"])
        assert leaders.confirm_matches(company, "Acme") and leaders.confirm_matches(company, "Acme agent")
    assert shown_name({"rank": "project", "display_name": "agent"}) == "agent"
