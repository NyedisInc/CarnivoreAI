import json
import sqlite3

from src.core.db import connect, db_path_for
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.swarm import legacy_pack_migration as legacy


def _legacy_copy_of_v75(tmp_path) -> sqlite3.Connection:
    (tmp_path / "fresh").mkdir()
    fresh = connect(db_path_for(tmp_path / "fresh"))
    run_chain(fresh, 0, 75)
    rows = fresh.execute("SELECT type, name, sql FROM sqlite_master WHERE name LIKE 'swarm\\_%' ESCAPE '\\' AND sql IS NOT NULL ORDER BY type DESC").fetchall()
    old = sqlite3.connect(":memory:")
    old.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    for (sql,) in fresh.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name IN ('projects', 'companies')"):
        old.execute(sql)
    for kind, name, sql in rows:
        if kind in ("table", "index") and "_fts_" not in name:
            old.execute(sql.replace("swarm_", "pack_"))
    for (sql,) in fresh.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND (name LIKE 'messaging\\_%' ESCAPE '\\' OR name LIKE 'crosstalk\\_%' ESCAPE '\\') AND name NOT LIKE '%\\_fts%' ESCAPE '\\' AND sql IS NOT NULL"):
        old.execute(sql)
    return old


def test_old_install_boots_into_swarm_names_and_a_second_boot_changes_nothing(tmp_path):
    old = _legacy_copy_of_v75(tmp_path)
    old.execute("PRAGMA foreign_keys = OFF")
    for message_id, source in (("m1", "pack"), ("m2", "crosstalk")):
        old.execute("INSERT INTO crosstalk_messages (id, source, thread, sender_key, receiver_key, sender_id, receiver_id, sender_name, "
                    "sender_provider, text, status, created_at, expires_at) VALUES (?, ?, 't', 'a', 'b', 'a', 'b', 'a', 'claude', 'x', 'queued', 0, 1)",
                    (message_id, source))
    old.execute("INSERT INTO crosstalk_contacts (pair_key, left_key, right_key, granted_at, source) VALUES ('a|b', 'a', 'b', 0, 'pack')")
    old.execute("INSERT INTO pack_agents (rank, slug, display_name, job, repo_dir, memory_scope, effort, character_seed, color_slot, thread_key, "
                "launch_profile, created_at, updated_at) VALUES ('project', 's', 'S', 'j', '/r', 'project', 'low', 1, 1, 't', 'pack-upper', 'x', 'x')")
    old.execute("INSERT INTO pack_deliveries (agent_id, authority, source, delivered_at) VALUES (1, 'data', 'pack_question', 'x')")
    before = {t: old.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for (t,) in old.execute("SELECT name FROM sqlite_master WHERE name LIKE 'pack\\_%' ESCAPE '\\' AND type = 'table'")}

    legacy_names = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE name LIKE 'pack\\_%' ESCAPE '\\'")}
    with old:
        run_chain(old, 75, CURRENT_SCHEMA_VERSION)
    names = {r[0] for r in old.execute("SELECT name FROM sqlite_master")}
    assert legacy_names and not (names & legacy_names), "no legacy pack_ table or index survives"
    assert {f"swarm_{t[len('pack_'):]}": c for t, c in before.items()} == {
        t: old.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in (f"swarm_{k[len('pack_'):]}" for k in before)}
    assert old.execute("SELECT source FROM swarm_deliveries").fetchone()[0] == "swarm_question"
    assert "swarm_agents_repo_slug" in names and "swarm_deliveries_agent" in names
    assert sorted(r[0] for r in old.execute("SELECT source FROM crosstalk_messages")) == ["crosstalk", "swarm"]
    assert old.execute("SELECT launch_profile FROM swarm_agents").fetchone()[0] == "swarm-upper"
    assert old.execute("SELECT source FROM crosstalk_contacts").fetchone()[0] == "swarm"
    with old:
        run_chain(old, 75, CURRENT_SCHEMA_VERSION)
    assert old.execute("SELECT source FROM swarm_deliveries").fetchone()[0] == "swarm_question"

    state = tmp_path / "state"
    (state / "pack" / "settings").mkdir(parents=True)
    (state / "pack" / "settings" / "1.json").write_text("{}")
    (state / "cplugs").mkdir()
    (state / "cplugs" / "state.json").write_text(json.dumps({"cplugs": {"huddle": {"enabled": True, "grants": ["pack", "other"]}}}))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "pack": {"flash_per_pack_per_hour": 7, "max_live_bodies": 3}, "pack_node_order": {"x": 1},
        "launch_profiles": {"revision": 1, "profiles": [{"id": "pack-upper"}, {"id": "mine"}]},
        "notification_routing": {"v": 1, "global": {"tick/screen/pack.alert": {"val": True, "ver": [1, "i"]},
                                                      "mute/pack.flash": {"val": True, "ver": [2, "i"]},
                                                      "default/other": {"val": True, "ver": [1, "i"]}},
                                 "local": {"tick/screen/pack.question_climbed": False}}}))

    assert legacy.migrate(config, state) == {"config": True, "folder": True, "grant": True}
    doc = json.loads(config.read_text())
    assert "pack" not in doc and "pack_node_order" not in doc
    assert doc["swarm"] == {"flash_per_swarm_per_hour": 7, "max_live_bodies": 3} and doc["swarm_node_order"] == {"x": 1}
    assert [p["id"] for p in doc["launch_profiles"]["profiles"]] == ["swarm-upper", "mine"]
    routing = doc["notification_routing"]
    assert set(routing["global"]) == {"tick/screen/swarm.alert", "mute/swarm.flash", "default/other"}
    assert routing["global"]["mute/swarm.flash"] == {"val": True, "ver": [2, "i"]} and set(routing["local"]) == {"tick/screen/swarm.question_climbed"}
    assert (state / "swarm" / "settings" / "1.json").exists() and not (state / "pack").exists()
    assert json.loads((state / "cplugs" / "state.json").read_text())["cplugs"]["huddle"]["grants"] == ["swarm", "other"]
    assert legacy.migrate(config, state) == {"config": False, "folder": False, "grant": False}
