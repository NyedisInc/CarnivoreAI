
from __future__ import annotations

import json

from tests.python.cplugs.save.old_sources_rig import BASE, C1, C2, rig  # noqa: F401


def test_verify_is_green_on_a_clean_run_and_names_the_point_whose_chunk_was_altered(rig) -> None:
    client, state, body = rig
    preview = client.post(f"{BASE}/imports/preview", json=body).json()
    run = client.post(f"{BASE}/imports/apply", json={**body, "fingerprint": preview["fingerprint"]}).json()["run_id"]
    clean = client.get(f"{BASE}/imports/{run}/verify").json()
    assert clean["ok"] is True and clean["points"] == {"checked": 3, "failed": 0} and clean["files"] == 4 and clean["failures"]["total"] == 0
    assert clean["reconciliation"]["unaccounted"] == 0 and clean["reconciliation"]["copies"] == 3
    manifests = state / "vault" / "manifests"
    chunk_sha = json.loads(next((manifests / C1).glob("*.json")).read_text())["files"][0]["chunks"][0][0]
    blob = next((state / "vault" / "blobs").rglob(f"{chunk_sha}.*"))
    blob.write_bytes(b"not the chunk that was filed")
    dirty = client.get(f"{BASE}/imports/{run}/verify").json()
    assert dirty["ok"] is False and dirty["points"] == {"checked": 3, "failed": 1}
    assert [f["unit"] for f in dirty["failures"]["first"]] == [C1] and "chunk" in dirty["failures"]["first"][0]["reason"]
    assert C2 not in {f["unit"] for f in dirty["failures"]["first"]}
