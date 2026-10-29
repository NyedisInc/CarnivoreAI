
import json
from pathlib import Path

from fastapi import FastAPI

from src.cplugs.host import routes as host_routes, runtime, state as owner_state
from src.cplugs.host.permission_renames import current_names


def test_current_names_maps_and_is_idempotent():
    assert current_names(["notify", "pack"]) == ("notify", "swarm")
    assert current_names(current_names(["pack", "swarm"])) == ("swarm",)


def test_stored_pack_grant_keeps_huddle_active(tmp_path: Path):
    (tmp_path / "cplugs").mkdir()
    (tmp_path / "cplugs" / "state.json").write_text(json.dumps({"version": 1, "cplugs": {"huddle": {
        "enabled": True, "revision": 4, "grants": ["sessions.read", "sessions.message", "notify", "agent_writes", "pack"]}}}))
    host = runtime.install(FastAPI(), tmp_path)
    d = runtime.find("huddle")
    row = host_routes.cplug_row(host, d)
    assert row["state"] == "active" and row["needs"] == []
    assert "swarm" in row["grants"]["app"] and "pack" not in row["grants"]["app"]
    owner_state.update(tmp_path, d.manifest, None, lambda st: st)
    stored = json.loads((tmp_path / "cplugs" / "state.json").read_text())["cplugs"]["huddle"]["grants"]
    assert "swarm" in stored and "pack" not in stored
