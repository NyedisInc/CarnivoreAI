
from __future__ import annotations

import json
from pathlib import Path

from src.cplugs.host import purge_kept, runtime
from src.cplugs.sdk.data_decl import parse_data
from tests.python.cplugs.owner import turn_on
from tests.python.cplugs.removability import _client

KEPT = {"id": "legacy_points", "kind": "folder", "state_path": "time-machine", "scope_by": "session_uuid",
        "policy": {"own": "excluded", "share": "excluded", "purge": "kept", "reason": "may hold the only copy"}}


def _old_tree(state: Path) -> list:
    point = state / "time-machine" / "proj" / "conv" / "20260101T000000Z-kill"
    point.mkdir(parents=True)
    files = [point / "meta.json", point / "transcript.jsonl.zst", state / "time-machine" / "limits.json"]
    for f in files:
        f.write_bytes(b"sole copy")
    (state / "vault-health.json").write_text(json.dumps({"legacy_unmigrated": 3, "available": False}))
    return files


def test_purging_save_keeps_the_old_tree_and_says_so(tmp_path: Path) -> None:
    files = _old_tree(tmp_path)
    client, host = _client(tmp_path)
    with client:
        turn_on(host, "save")
        revision = client.get("/api/v1/cplugs/save").json()["revision"]
        assert client.put("/api/v1/cplugs/save", json={"revision": revision, "enabled": False}).status_code == 200
        price = client.post("/api/v1/cplugs/save/purge", json={"dry_run": True}).json()
        kept = {k["id"]: k for k in price["kept_stores"]}
        assert kept["legacy_points"]["location"] == str(tmp_path / "time-machine") and kept["legacy_points"]["exists"] is True
        assert kept["legacy_points"]["reason"]
        done = client.post("/api/v1/cplugs/save/purge", json={"dry_run": False, "confirm_token": price["confirm_token"]})
        assert done.status_code == 200, done.text
        kept_after = {k["id"]: k for k in done.json()["kept_stores"]}
        assert "legacy_points" in kept_after and kept_after["vault"]["location"] == str(tmp_path / "vault")
    assert all(f.read_bytes() == b"sole copy" for f in files), "a purge deleted the old restore point tree"
    assert not host.folder("save").exists()


def test_a_kept_path_in_owns_files_is_still_not_deletable() -> None:
    decls = parse_data([KEPT], {})
    assert purge_kept.deletable_owned_files(("time-machine", "other.db"), decls) == ("other.db",)
    assert purge_kept.deletable_owned_files(("time-machine/proj",), decls) == ()
    assert purge_kept.deletable_owned_files(("x",), decls) == ("x",)
    assert purge_kept.deletable_owned_files(("time-machine",), ()) == ("time-machine",)


def test_the_shipped_save_sidecar_does_not_list_the_tree_in_owns_files() -> None:
    save = runtime.find("save")
    assert save is not None and "time-machine" not in save.manifest.owns.files
    assert any(d.state_path == "time-machine" and d.outlives_purge for d in save.manifest.data or ())
