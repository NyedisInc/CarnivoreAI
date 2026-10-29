
from __future__ import annotations

from tests.python.cplugs.save.old_sources_rig import BASE, C1, C2, rig, snapshot  # noqa: F401


def test_preview_writes_nothing_apply_files_it_a_rerun_files_nothing_and_undo_restores_the_vault(rig) -> None:
    client, state, body = rig
    vault = state / "vault"
    before = snapshot(vault)
    preview = client.post(f"{BASE}/imports/preview", json=body)
    assert preview.status_code == 200, preview.text
    counts = preview.json()["counts"]
    assert counts["points"] == {"total": 2, "current": 2, "kept": 0} and counts["copies"]["covered"] == 1 and counts["extras"]["files"] == 2
    assert snapshot(vault) == before
    assert [p.name for p in (state / "cplugs" / "save" / "imports").iterdir()] == ["previews.json"]
    stale = client.post(f"{BASE}/imports/apply", json={**body, "fingerprint": "0" * 64})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "plan_changed" and snapshot(vault) == before
    applied = client.post(f"{BASE}/imports/apply", json={**body, "fingerprint": preview.json()["fingerprint"]})
    assert applied.status_code == 200, applied.text
    receipt = applied.json()
    assert receipt["state"] == "done" and receipt["filed"] == {"adopted": 3}
    manifests = vault / "manifests"
    assert sorted(p.name for p in manifests.iterdir()) == sorted([C1, C2, "save.old-archive-extras"])
    assert len(list((manifests / C1).glob("*.tags"))) == 1 and len(list((manifests / C1).glob("*.json"))) == 1
    after = snapshot(vault)
    again = client.post(f"{BASE}/imports/preview", json=body).json()
    assert again["counts"]["points"]["total"] == 0
    rerun = client.post(f"{BASE}/imports/apply", json={**body, "fingerprint": again["fingerprint"]}).json()
    assert rerun["filed"] == {"present": 1} and snapshot(vault) == after
    assert {r["run_id"] for r in client.get(f"{BASE}/imports").json()["imports"]} == {receipt["run_id"], rerun["run_id"]}
    undone = client.post(f"{BASE}/imports/{receipt['run_id']}/undo")
    assert undone.status_code == 200 and len(undone.json()["undo"]["removed"]) == 3 and not undone.json()["undo"]["errors"]
    assert snapshot(vault) == before
    assert client.post(f"{BASE}/imports/{receipt['run_id']}/undo").status_code == 409


def test_an_archived_project_is_no_known_project(rig, monkeypatch) -> None:
    from src.cplugs.sdk import vault_sources

    client, _state, body = rig
    row = {"uid": "p1", "root": "/gone", "display_name": "home", "archived_at": "2026-09-08T00:00:00Z"}
    monkeypatch.setattr(vault_sources, "project_roots", lambda _state: [row])
    assert client.post(f"{BASE}/imports/preview", json=body).json()["counts"]["no_project"] == 2
    row["archived_at"] = None
    assert client.post(f"{BASE}/imports/preview", json=body).json()["counts"]["no_project"] == 0
