
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest
import structlog

from src.cplugs.crate import constants as K
from src.cplugs.crate.jobs import runner
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.api_world import BASE, ApiWorld, export, stop_runner, wait_job
from tests.python.cplugs.crate.crate_world import UUID_A
from tests.python.cplugs.crate.test_jobs import _bundle_ids, _forget

SESSION = {"scope": "session", "target": UUID_A, "variant": "own"}
ROUTES = [("get", "/summary"), ("post", "/plan"), ("post", "/exports"), ("get", "/jobs"), ("get", "/jobs/j"),
          ("post", "/jobs/j/cancel"), ("get", "/bundles"), ("get", "/bundles/b-x"), ("post", "/bundles/b-x/contents"),
          ("post", "/bundles/b-x/verify"), ("post", "/bundles/b-x/copies"), ("post", "/bundles/b-x/extract"),
          ("get", "/folders/primary/crates"), ("post", "/folders/primary/crates/n/contents"),
          ("post", "/folders/primary/crates/n/verify"), ("post", "/folders/primary/crates/n/extract")]


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def test_every_route_needs_the_bearer_and_answers_409_while_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert len(ROUTES) == 16
    off = ApiWorld(tmp_path, monkeypatch, on=False)
    with off.client(authed=False) as anonymous:
        for method, path in ROUTES:
            answer = getattr(anonymous, method)(BASE + path, **({"json": {}} if method == "post" else {}))
            assert answer.status_code == 401, (path, answer.status_code)
    with off.client() as client:
        for method, path in ROUTES:
            answer = getattr(client, method)(BASE + path, **({"json": {}} if method == "post" else {}))
            assert answer.status_code == 409 and answer.json()["detail"]["code"] == "cplug_disabled", path


def test_plan_export_jobs_bundles_contents_and_extract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        summary = client.get(f"{BASE}/summary").json()
        assert summary["folders"]["primary"]["state"] == K.FOLDER_OK and summary["folders"]["second"] is None
        assert summary["running_job"] is None and isinstance(summary["bundles"], int)
        plan = client.post(f"{BASE}/plan", json=SESSION).json()
        assert {"ok", "fingerprint", "conversations", "reconcile", "blockers", "warnings", "estimate_bytes",
                "folder"} <= set(plan) and plan["ok"]
        changed = client.post(f"{BASE}/exports", json={**SESSION, "fingerprint": "0" * 64})
        assert changed.status_code == 409 and changed.json()["detail"]["code"] == "plan_changed"
        assert changed.json()["detail"]["detail"]["fingerprint"] == plan["fingerprint"]
        done = export(api, client, SESSION)
        assert done.state == K.STATE_DONE, done.error
        bundle_id = done.result["bundle_id"]
        assert f"cplug.crate.jobs:{done.job_id}" in api.published
        assert done.result["encrypted"] is False and isinstance(done.result["findings"], int)
        view = client.get(f"{BASE}/jobs/{done.job_id}").json()
        assert view["state"] == "done" and view["result"]["bundle_id"] == bundle_id
        assert client.get(f"{BASE}/jobs").json()["jobs"][0]["job_id"] == done.job_id
        assert client.get(f"{BASE}/jobs/job-19700101T000000Z-00000000").status_code == 404
        listed = {b["bundle_id"]: b for b in client.get(f"{BASE}/bundles").json()["bundles"]}
        assert listed[bundle_id]["locations"][0]["state"] == K.LOCATION_PRESENT
        mine = client.get(f"{BASE}/bundles", params={"project": api.world.p1}).json()["bundles"]
        assert {b["bundle_id"] for b in mine} == {"crate-p", "crate-a", bundle_id}
        other = client.get(f"{BASE}/bundles", params={"project": api.world.p2}).json()["bundles"]
        assert [b["bundle_id"] for b in other] == ["crate-d"]
        unknown = client.get(f"{BASE}/bundles", params={"project": 999999})
        assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "project_not_found"
        one = client.get(f"{BASE}/bundles/{bundle_id}").json()
        assert one["encrypted"] is False and one["manifest"]["variant"] == "own"
        conv = one["manifest"]["conversations"][0]["id"]
        contents = client.post(f"{BASE}/bundles/{bundle_id}/contents", json={}).json()
        assert contents["files"] and "tables" in contents
        out = client.post(f"{BASE}/bundles/{bundle_id}/extract", json={"conversation_id": conv}).json()
        dest = Path(out["dest"])
        assert dest.parent == api.env.work / K.EXTRACT_DIR and dest.is_dir() and out["resume_hint"].startswith("claude")
        missing = client.post(f"{BASE}/bundles/{bundle_id}/extract", json={"conversation_id": "zzzzzzzz-none"})
        assert missing.status_code == 404 and missing.json()["detail"]["code"] == "conversation_not_in_crate"
        crates = client.get(f"{BASE}/folders/primary/crates").json()["crates"]
        name = crates[0]["name"]
        assert crates[0]["bundle_id"] == bundle_id
        assert client.post(f"{BASE}/folders/primary/crates/{name}/contents").json()["manifest"]["bundle_id"] == bundle_id
        verified = client.post(f"{BASE}/bundles/{bundle_id}/verify", json={"level": "full"})
        assert verified.status_code == 202
        rec = wait_job(api, verified.json()["job_id"])
        assert rec.state == K.STATE_DONE and rec.result["recorded"] == bundle_id
        assert client.get(f"{BASE}/bundles/{bundle_id}").json()["bundle"]["verified_at"]


def test_job_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    gate = threading.Event()
    runner.start(api.env.work, K.KIND_VERIFY, {}, lambda h: {"ok": gate.wait(30)}, notify=lambda n, k: None)
    try:
        with api.client() as client:
            plan = client.post(f"{BASE}/plan", json=SESSION).json()
            busy = client.post(f"{BASE}/exports", json={**SESSION, "fingerprint": plan["fingerprint"]})
            assert busy.status_code == 409 and busy.json()["detail"]["code"] == "job_busy"
            assert client.get(f"{BASE}/summary").json()["running_job"]["state"] == "running"
    finally:
        gate.set()


def test_folder_names_are_checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    folder = Path(api.world.state) / K.DEFAULT_FOLDER
    folder.mkdir(exist_ok=True)
    outside = tmp_path / "elsewhere.crate"
    outside.write_bytes(b"x")
    os.symlink(outside, folder / "crate-20261017T000000Z-session-deadbeef.crate")
    with api.client() as client:
        for name, code in (("...", "bad_crate_name"), ("notes.txt", "bad_crate_name"),
                           ("crate-20261017T000000Z-session-deadbeef.crate", "crate_refused")):
            refused = client.post(f"{BASE}/folders/primary/crates/{name}/contents", json={})
            assert refused.status_code == 422 and refused.json()["detail"]["code"] == code, name
        for name in ("..", "..%2Fx"):
            assert client.post(f"{BASE}/folders/primary/crates/{name}/contents", json={}).status_code in (404, 422)
        assert client.get(f"{BASE}/folders/third/crates").status_code == 422
        gone = client.post(f"{BASE}/folders/primary/crates/crate-20261017T000000Z-session-00000000.crate/contents")
        assert gone.status_code == 404 and gone.json()["detail"]["code"] == "crate_not_found"


def test_the_identity_never_reaches_a_log_a_job_record_or_an_answer(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    identity, recipient = cf.generate()
    api = ApiWorld(tmp_path, monkeypatch)
    texts = []
    with structlog.testing.capture_logs() as logs, api.client() as client:
        done = export(api, client, {**SESSION, "encrypt": True, "recipients": [recipient]})
        assert done.state == K.STATE_DONE, done.error
        bundle_id = done.result["bundle_id"]
        need = client.post(f"{BASE}/bundles/{bundle_id}/contents", json={})
        assert need.status_code == 409 and need.json()["detail"]["code"] == "needs_identity"
        wrong, _ = cf.generate()
        assert client.post(f"{BASE}/bundles/{bundle_id}/contents", json={"identity": wrong}).status_code == 403
        bad = client.post(f"{BASE}/bundles/{bundle_id}/contents", json={"identity": "AGE-SECRET-KEY-1NOPE"})
        assert bad.status_code == 422 and "NOPE" not in bad.text
        for path, body in (("contents", {"identity": identity}), ("verify", {"level": "drill", "identity": identity})):
            answer = client.post(f"{BASE}/bundles/{bundle_id}/{path}", json=body)
            texts.append(answer.text)
            assert answer.status_code in (200, 202), answer.text
        rec = wait_job(api, json.loads(texts[-1])["job_id"])
        assert rec.state == K.STATE_DONE and rec.result["locations"][0]["ok"], rec.error
        conv = json.loads(texts[0])["manifest"]["conversations"][0]["id"]
        texts.append(client.post(f"{BASE}/bundles/{bundle_id}/extract",
                                 json={"conversation_id": conv, "identity": identity}).text)
        texts += [client.get(f"{BASE}/jobs").text, client.get(f"{BASE}/summary").text]
    secret = identity.upper()
    assert all(secret not in t.upper() for t in texts)
    assert secret not in repr(logs).upper()
    for path in api.jobs_root().iterdir():
        assert secret not in path.read_text().upper()
    assert not any(p.name.startswith(K.DRILL_PREFIX) for p in (api.env.work / K.EXTRACT_DIR).iterdir())


def test_a_folder_verify_records_a_lost_own_crate_of_this_install(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        done = export(api, client, SESSION)
        bundle_id, name = done.result["bundle_id"], done.result["file_name"]
        _forget(Path(api.world.state), bundle_id)
        quick = client.post(f"{BASE}/folders/primary/crates/{name}/verify", json={"level": "quick"})
        assert wait_job(api, quick.json()["job_id"]).result["recorded"] is None
        assert bundle_id not in _bundle_ids(Path(api.world.state))
        full = client.post(f"{BASE}/folders/primary/crates/{name}/verify", json={"level": "full"})
        rec = wait_job(api, full.json()["job_id"])
        assert rec.state == K.STATE_DONE and rec.result["recorded"] == bundle_id
        assert _bundle_ids(Path(api.world.state)).count(bundle_id) == 1
        again = client.post(f"{BASE}/folders/primary/crates/{name}/verify", json={"level": "full"})
        assert wait_job(api, again.json()["job_id"]).result["recorded"] == bundle_id
        assert _bundle_ids(Path(api.world.state)).count(bundle_id) == 1


def test_a_failed_verify_records_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        done = export(api, client, SESSION)
        path = Path(done.result["path"])
        before = client.get(f"{BASE}/bundles/{done.result['bundle_id']}").json()["bundle"]
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0xFF
        path.write_bytes(bytes(data))
        failed = client.post(f"{BASE}/bundles/{done.result['bundle_id']}/verify", json={"level": "full"})
        rec = wait_job(api, failed.json()["job_id"])
        assert rec.state == K.STATE_FAILED and rec.error["code"] == "sha_mismatch"
        assert client.get(f"{BASE}/bundles/{done.result['bundle_id']}").json()["bundle"] == before
