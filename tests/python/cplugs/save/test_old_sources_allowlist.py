
from __future__ import annotations

from src.cplugs.save import import_service as svc
from src.cplugs.save.service import RUNTIME
from tests.python.cplugs.save.old_sources_rig import BASE, C1, C2, rig, snapshot  # noqa: F401


def _points(body: dict) -> list:
    vault = RUNTIME.vault()
    built = svc._built(vault, svc.config_of(body, vault.root))
    return sorted(({"id": p.unit, "point_id": p.point_id} for p in built.plan.points), key=lambda r: r["id"])


def test_only_the_listed_points_are_filed_the_rest_are_not_selected(rig) -> None:
    client, state, body = rig
    vault = state / "vault"
    before = snapshot(vault)
    everything = client.post(f"{BASE}/imports/preview", json=body).json()
    assert everything["counts"]["points"]["total"] == 2
    keep = [p for p in _points(body) if p["id"] == C1]
    assert len(keep) == 1
    only = {**body, "only_points": keep}
    preview = client.post(f"{BASE}/imports/preview", json=only).json()
    assert preview["fingerprint"] != everything["fingerprint"]
    copies = preview["counts"]["copies"]
    assert preview["counts"]["points"]["total"] == 1 and copies["skip:not_selected"] == 1
    assert sum(v for k, v in copies.items() if k != "total") == copies["total"]
    unknown = client.post(f"{BASE}/imports/preview", json={**body, "only_points": [{"id": C1, "point_id": "20200101T000000Z-import"}]})
    assert unknown.status_code == 400 and unknown.json()["detail"]["code"] == "unknown_point"
    other = client.post(f"{BASE}/imports/apply", json={**body, "only_points": [p for p in _points(body) if p["id"] == C2],
                                                       "fingerprint": preview["fingerprint"]})
    assert other.status_code == 409 and other.json()["detail"]["code"] == "plan_changed" and snapshot(vault) == before
    applied = client.post(f"{BASE}/imports/apply", json={**only, "fingerprint": preview["fingerprint"]})
    assert applied.status_code == 200, applied.text
    receipt = applied.json()
    assert sorted(p.name for p in (vault / "manifests").iterdir()) == sorted([C1, "save.old-archive-extras"])
    check = client.get(f"{BASE}/imports/{receipt['run_id']}/verify").json()
    assert check["ok"] and check["reconciliation"]["unaccounted"] == 0 and check["reconciliation"]["buckets"]["skip:not_selected"] == 1
