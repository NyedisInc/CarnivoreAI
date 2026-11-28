
import json
from pathlib import Path

from fastapi import FastAPI

from src.plugins.host import registry_store, routes as host_routes, runtime, state as owner_state
from src.plugins.host.permission_renames import current_names


def test_current_names_maps_and_is_idempotent():
    assert current_names(["notify", "pack"]) == ("notify", "swarm")
    assert current_names(current_names(["pack", "swarm"])) == ("swarm",)


def test_stored_pack_grant_keeps_huddle_active(tmp_path: Path):
    reg_path = registry_store.registry_path(tmp_path)
    reg_path.parent.mkdir(parents=True)
    doc = registry_store.new_document()
    doc["items"]["huddle"] = {
        "kind": "feature",
        "enabled": True,
        "revision": 4,
        "grants": ["sessions.read", "sessions.message", "notify", "agent_writes", "pack"],
    }
    reg_path.write_text(json.dumps(doc))
    host = runtime.install(FastAPI(), tmp_path)
    d = runtime.find("taskmanager")
    row = host_routes.cplug_row(host, d)
    assert row["state"] == "active" and row["needs"] == []
    assert "swarm" in row["grants"]["app"] and "pack" not in row["grants"]["app"]
    owner_state.update(tmp_path, d.manifest, None, lambda st: st)
    stored = json.loads(reg_path.read_text())["items"]["taskmanager"]["grants"]
    assert "swarm" in stored and "pack" not in stored
