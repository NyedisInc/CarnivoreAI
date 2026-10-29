
from __future__ import annotations

import asyncio
import hashlib
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from src.core.crate_import import apply as ap
from src.core.crate_import import hooks as hk
from src.core.crate_import import undo
from src.core.crate_import.plan import build_plan
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.db import connect, db_path_for, set_meta
from src.core.exports.store import crate_written_key
from src.cplugs.crate import constants as K
from src.cplugs.crate import import_store, imports, mcp
from src.cplugs.crate.jobs import state
from src.cplugs.crate.jobs.sweep import sweep_interrupted
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.api_world import BASE, ApiWorld, export, stop_runner, wait_job
from tests.python.cplugs.crate.test_mcp import _call
from tests.python.crate_import.install import Install, make_install

@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def restore_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    (tmp_path / "src").mkdir()
    api = ApiWorld(tmp_path / "src", monkeypatch)
    client = api.client()
    done = export(api, client, {"scope": "project", "target": api.world.root1, "variant": "own"})
    assert done.state == "done", done.error
    bundle_id = done.result["bundle_id"]
    path = Path(done.result["path"])
    with cf.open_crate(path) as reader:
        install_id = reader.manifest.source["install_id"]
    (tmp_path / "t").mkdir()
    install = make_install(tmp_path / "t", install_id=install_id)
    with closing(install.db()) as conn:
        set_meta(conn, crate_written_key(bundle_id), done.result["sha256"])
        conn.commit()
    monkeypatch.setattr(imports, "import_env_of", lambda env: install.env)
    return SimpleNamespace(api=api, client=client, bundle_id=bundle_id, install=install, source={"bundle_id": bundle_id},
                           sha256=done.result["sha256"], path=path)


def plan_body(world: SimpleNamespace, **extra: Any) -> Dict[str, Any]:
    return {"source": world.source, **extra}


def test_restore_runs_as_a_job_and_leaves_a_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = restore_world(tmp_path, monkeypatch)
    planned = w.client.post(f"{BASE}/imports/plan", json=plan_body(w))
    assert planned.status_code == 200 and planned.json()["ok"], planned.text
    assert planned.json()["start_available"] is True
    fingerprint = planned.json()["fingerprint"]

    stale = w.client.post(f"{BASE}/imports", json={**plan_body(w), "fingerprint": "0" * 64})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "plan_changed"
    assert stale.json()["detail"]["detail"]["fingerprint"] == fingerprint
    assert w.client.get(f"{BASE}/imports").json() == {"imports": []}

    started = w.client.post(f"{BASE}/imports", json={**plan_body(w), "fingerprint": fingerprint})
    assert started.status_code == 202, started.text
    job = wait_job(w.api, started.json()["job_id"])
    assert job.kind == "import" and job.state == "done", job.error
    receipt = job.result
    assert receipt["import_id"] == started.json()["import_id"] and receipt["state"] in ("done", "done_with_warnings")
    assert receipt["sessions"] and all(s["asleep"] and s["conversation_id"] for s in receipt["sessions"])
    with closing(connect(db_path_for(w.install.state), create=False)) as conn:
        local = {r[0] for r in conn.execute("SELECT session_uuid FROM sessions")}
    assert {s["session_uuid"] for s in receipt["sessions"]} == local

    listed = w.client.get(f"{BASE}/imports").json()["imports"]
    assert [r["import_id"] for r in listed] == [receipt["import_id"]]
    one = w.client.get(f"{BASE}/imports/{receipt['import_id']}")
    assert one.status_code == 200 and one.json()["bundle_id"] == w.bundle_id
    assert w.client.get(f"{BASE}/imports/imp-20200101T000000Z-00000000").status_code == 404
    assert w.client.get(f"{BASE}/imports/not-an-id").status_code == 404

    again = w.client.post(f"{BASE}/imports/plan", json=plan_body(w)).json()
    assert again["fingerprint"] != fingerprint


def test_restore_needs_the_imports_write_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = restore_world(tmp_path, monkeypatch)
    fingerprint = w.client.post(f"{BASE}/imports/plan", json=plan_body(w)).json()["fingerprint"]
    monkeypatch.setattr(type(w.api.ctx), "has", lambda self, permission: permission != "imports.write")
    refused = w.client.post(f"{BASE}/imports", json={**plan_body(w), "fingerprint": fingerprint})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "permission_missing"
    with closing(connect(db_path_for(w.install.state), create=False)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_mcp_refuses_made_here_and_identity_and_waits_in_the_inbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = restore_world(tmp_path, monkeypatch)
    ok, text = _call(w.api, "crate_import_preview", {"bundle_id": w.bundle_id, "made_here": True})
    assert not ok and "made_here is refused" in text
    ok, text = _call(w.api, "crate_import", {"bundle_id": w.bundle_id, "made_here": True, "fingerprint": "0" * 64})
    assert not ok and "made_here is refused" in text
    ok, text = _call(w.api, "crate_import_preview", {"bundle_id": w.bundle_id, "identity": "AGE-SECRET-KEY-1X"})
    assert not ok and "identity is refused" in text

    spec = mcp.TOOLS["crate_import"]
    assert spec.gate == "inbox" and spec.prepare and "fingerprint" in spec.properties
    ok, plan = _call(w.api, "crate_import_preview", {"bundle_id": w.bundle_id})
    assert ok and plan["ok"]
    shown, sentence = asyncio.run(spec.prepare(w.api.ctx, SimpleNamespace(), {"bundle_id": w.bundle_id, "fingerprint": plan["fingerprint"]}))
    assert "asleep" in sentence and shown["fingerprint"] == plan["fingerprint"]
    ok, text = _call(w.api, "crate_imports_list", {})
    assert ok and text["imports"] == []


def _running_import_job(w: SimpleNamespace, import_id: str) -> state.JobRecord:
    root = state.jobs_dir(w.api.env.work)
    rec = state.JobRecord(job_id=state.new_job_id(), kind=K.KIND_IMPORT, created_at=1.0, updated_at=1.0,
                          request={"import_id": import_id, "source": w.source, "crate_sha256": w.sha256, "encrypted": False,
                                   "options": ImportRequest().as_json()})
    state.save(root, rec)
    return rec


def test_the_sweep_undoes_the_files_of_an_import_killed_before_the_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = restore_world(tmp_path, monkeypatch)
    import_id = new_import_id()
    placed = w.install.claude / "projects" / "-x" / "left-over.jsonl"
    placed.parent.mkdir(parents=True)
    placed.write_bytes(b"{}\n")
    entry = undo.file_entry(placed, hashlib.sha256(b"{}\n").hexdigest(), 3)
    import_store.append_undo(w.api.env.work, import_id, entry)
    rec = _running_import_job(w, import_id)
    assert sweep_interrupted(w.api.env) == 1
    ended = state.load(state.jobs_dir(w.api.env.work), rec.job_id)
    assert ended.state == "failed" and ended.error["code"] == K.E_INTERRUPTED_UNDONE
    assert not placed.exists()


class Crash(BaseException):
    pass


class CrashAfterRows(hk.ApplyHooks):

    def __init__(self, work: Path, import_id: str) -> None:
        self.work, self.import_id = work, import_id

    def undo(self, entry: Dict[str, Any]) -> None:
        import_store.append_undo(self.work, self.import_id, entry)

    def checkpoint(self, name: str) -> None:
        if name == hk.CP_AFTER_ROWS:
            raise Crash()


def test_the_sweep_rolls_an_import_forward_when_the_rows_are_committed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = restore_world(tmp_path, monkeypatch)
    import_id = new_import_id()
    with cf.open_crate(w.path) as reader:
        shown = build_plan(reader, w.install.env, ImportRequest(), crate_sha256=w.sha256, encrypted=False)
        with pytest.raises(Crash):
            ap.apply_import(reader, w.install.env, ImportRequest(), crate_sha256=w.sha256, fingerprint=shown["fingerprint"],
                            import_id=import_id, hooks=CrashAfterRows(w.api.env.work, import_id))
    rec = _running_import_job(w, import_id)
    assert sweep_interrupted(w.api.env) == 1
    ended = state.load(state.jobs_dir(w.api.env.work), rec.job_id)
    assert ended.state == "done" and ended.result["interrupted_resumed"] is True, ended.error
    assert import_store.read_receipt(w.api.env.work, import_id)["import_id"] == import_id
    assert [r["import_id"] for r in w.client.get(f"{BASE}/imports").json()["imports"]] == [import_id]
