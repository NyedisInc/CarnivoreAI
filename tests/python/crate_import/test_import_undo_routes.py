
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.crate_import import apply as ap
from src.core.crate_import import ledger
from src.core.crate_import.model import ImportRequest, new_import_id
from src.core.crate_import.plan import build_plan
from src.core.db import connect, db_path_for
from src.cplugs.crate import import_store, import_undo, mcp
from src.cplugs.crate.jobs import runner
from src.cplugs.crate.jobs.sweep import sweep_interrupted
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.api_world import BASE, stop_runner, wait_job
from tests.python.cplugs.crate.test_mcp import _call
from tests.python.crate_import.test_import_routes import (  # noqa: F401
    Crash, CrashAfterRows, _running_import_job, free_slot, plan_body, restore_world,
)


def restored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    w = restore_world(tmp_path, monkeypatch)
    fingerprint = w.client.post(f"{BASE}/imports/plan", json=plan_body(w)).json()["fingerprint"]
    started = w.client.post(f"{BASE}/imports", json={**plan_body(w), "fingerprint": fingerprint})
    assert started.status_code == 202, started.text
    assert wait_job(w.api, started.json()["job_id"]).state == "done"
    return w, started.json()["import_id"]


def counts(w: SimpleNamespace) -> tuple:
    with closing(connect(db_path_for(w.install.state), create=False)) as conn:
        return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]


def test_preview_then_undo_empties_the_install_and_marks_the_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, import_id = restored(tmp_path, monkeypatch)
    assert counts(w)[0] > 0
    preview = w.client.get(f"{BASE}/imports/{import_id}/undo")
    assert preview.status_code == 200 and preview.json()["ok"] and preview.json()["rows_to_remove"] > 0, preview.text
    assert counts(w)[0] > 0, "a preview writes nothing"
    w.api.published.clear()

    done = w.client.post(f"{BASE}/imports/{import_id}/undo")

    assert done.status_code == 200, done.text
    body = done.json()
    assert body["state"] == "undone" and body["undo"]["rows"]["deleted"] > 0 and body["undo"]["kept"] == []
    assert counts(w) == (0, 0) or counts(w)[0] == 0
    assert "cplug.crate.jobs" in w.api.published
    listed = w.client.get(f"{BASE}/imports").json()["imports"]
    assert [(r["import_id"], r["state"]) for r in listed] == [(import_id, "undone")]
    assert w.client.get(f"{BASE}/imports/{import_id}").json()["undo"]["rows"]["deleted"] == body["undo"]["rows"]["deleted"]
    again = w.client.post(f"{BASE}/imports/{import_id}/undo")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_undone"
    assert w.client.get(f"{BASE}/imports/{import_id}/undo").status_code == 409
    assert w.client.post(f"{BASE}/imports/imp-20200101T000000Z-00000000/undo").status_code == 404
    assert w.client.post(f"{BASE}/imports/not-an-id/undo").status_code == 404


def test_undo_needs_the_imports_write_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, import_id = restored(tmp_path, monkeypatch)
    before = counts(w)
    monkeypatch.setattr(type(w.api.ctx), "has", lambda self, permission: permission != "imports.write")
    refused = w.client.post(f"{BASE}/imports/{import_id}/undo")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "permission_missing"
    assert counts(w) == before


def test_a_running_crate_job_refuses_the_undo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, import_id = restored(tmp_path, monkeypatch)
    before = counts(w)
    monkeypatch.setattr(runner, "running_request", lambda: {"kind": "verify"})
    busy = w.client.post(f"{BASE}/imports/{import_id}/undo")
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "job_busy"
    preview = w.client.get(f"{BASE}/imports/{import_id}/undo").json()
    assert preview["ok"] is False and "job_busy" in {b["code"] for b in preview["blockers"]}
    assert counts(w) == before


def test_a_later_restore_from_the_same_source_blocks_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, import_id = restored(tmp_path, monkeypatch)
    before = counts(w)
    with closing(connect(db_path_for(w.install.state), create=False)) as conn:
        entry = ledger.read_entry(conn, import_id)
        ledger.write_entry(conn, "imp-29991231T000000Z-ffffffff", {**entry, "key_map": {}})
        conn.commit()
    blocked = w.client.post(f"{BASE}/imports/{import_id}/undo")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "undo_blocked"
    assert [b["code"] for b in blocked.json()["detail"]["detail"]] == ["later_import"]
    assert counts(w) == before and import_store.read_receipt(w.api.env.work, import_id)["state"] != "undone"


def test_a_restore_the_sweep_had_to_finish_cannot_be_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = restore_world(tmp_path, monkeypatch)
    import_id = new_import_id()
    with cf.open_crate(w.path) as reader:
        shown = build_plan(reader, w.install.env, ImportRequest(), crate_sha256=w.sha256, encrypted=False)
        with pytest.raises(Crash):
            ap.apply_import(reader, w.install.env, ImportRequest(), crate_sha256=w.sha256, fingerprint=shown["fingerprint"],
                            import_id=import_id, hooks=CrashAfterRows(w.api.env.work, import_id))
    _running_import_job(w, import_id)
    assert sweep_interrupted(w.api.env) == 1
    before = counts(w)
    preview = w.client.get(f"{BASE}/imports/{import_id}/undo").json()
    assert preview["ok"] is False and [b["code"] for b in preview["blockers"]] == ["record_incomplete"]
    refused = w.client.post(f"{BASE}/imports/{import_id}/undo")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "undo_blocked" and counts(w) == before


def test_the_tool_waits_in_the_inbox_says_what_it_approves_and_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w, import_id = restored(tmp_path, monkeypatch)
    spec = mcp.TOOLS["crate_import_undo"]
    assert spec.gate == "inbox" and spec.prepare and tuple(spec.dedupe_by) == ("import_id",)
    shown, sentence = asyncio.run(spec.prepare(w.api.ctx, SimpleNamespace(), {"import_id": import_id}))
    assert shown == {"import_id": import_id} and import_id in sentence and "database row" in sentence and "already here" in sentence
    ok, text = _call(w.api, "crate_import_undo", {"import_id": "nope"})
    assert not ok and "import_id" in text
    result = asyncio.run(spec.handler(w.api.ctx, SimpleNamespace(), shown))
    assert "undone" in str(result) and counts(w)[0] == 0, result
    with pytest.raises(mcp.ToolError, match="already_undone"):
        asyncio.run(spec.prepare(w.api.ctx, SimpleNamespace(), {"import_id": import_id}))
