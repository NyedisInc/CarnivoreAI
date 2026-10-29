
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts.crate import flows
from scripts.crate.client import sha256_of
from src.core.blobcodec.place import sha256_file
from src.cplugs.crate import folders, import_store
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.api_world import stop_runner
from tests.python.crate_headless.world import TwoInstalls


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def relocated(w: TwoInstalls) -> str:
    return str(w.install.projects / "Proj One")


def exported_and_sent(w: TwoInstalls, tmp_path: Path) -> Dict[str, Any]:
    exported = flows.export_crate(w.client_a, flows.export_body("project", w.a.world.root1))
    sent = flows.send_crate(w.client_a, w.client_b, exported["bundle_id"], workdir=tmp_path)
    assert sent["sha256"] == exported["sha256"]
    return sent


def logged_files(w: TwoInstalls, import_id: str) -> List[Dict[str, Any]]:
    return [e for e in import_store.read_undo(w.b.env.work, import_id) if e.get("op") == "file"]


def test_a_foreign_crate_round_trips_between_two_installs_and_undoes_to_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    assert w.b_counts() == {"sessions": 0, "projects": 0}
    sent = exported_and_sent(w, tmp_path)

    on_b = folders.resolve(w.b.env, "primary") / sent["name"]
    assert sha256_of(on_b) == sent["sha256"] and on_b.stat().st_size == sent["size"]

    body = flows.import_body(sent["name"], relocate=relocated(w))
    assert "made_here" not in body
    plan = w.client_b.plan_import(body)
    assert plan["ok"] and plan["blockers"] == []
    assert plan["provenance"] == "foreign" and plan["provenance_reason"] == "other_computer"

    done = flows.restore_crate(w.client_b, sent["name"], relocate=relocated(w))
    receipt = done["receipt"]
    assert done["provenance"] == "foreign" and receipt["provenance"] == "foreign"
    assert receipt["state"] in ("done", "done_with_warnings") and receipt["crate_sha256"] == sent["sha256"]
    assert w.b_counts() == {"sessions": 2, "projects": 1}
    assert all(s["asleep"] for s in receipt["sessions"])

    report = flows.verify_import(w.client_b, done["import_id"], crate_sha256=sent["sha256"])
    assert report["ok"] and report["files_written"] == receipt["files"]["written"] > 0 and report["sessions"] == 2

    entries = logged_files(w, done["import_id"])
    assert len(entries) >= receipt["files"]["written"]
    with cf.open_crate(on_b) as reader:
        crate_shas = {record.content_sha256 for record in reader.files()}
    for entry in entries:
        assert sha256_file(entry["path"]) == entry["sha256"], entry["path"]
    assert sum(1 for e in entries if e["sha256"] in crate_shas) > 0

    listed = w.client_b.imports()["imports"]
    assert [r["import_id"] for r in listed] == [done["import_id"]]

    undone = flows.undo_import(w.client_b, done["import_id"])
    assert undone["preview"]["ok"] and undone["result"]["state"] == "undone"
    assert w.b_counts() == {"sessions": 0, "projects": 0}
    assert not any(Path(e["path"]).exists() for e in entries)
    assert w.client_b.receipt(done["import_id"])["state"] == "undone"


def test_cycle_runs_every_step_and_rolls_back_on_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = TwoInstalls(tmp_path, monkeypatch)
    answer = flows.cycle(w.client_a, w.client_b, flows.export_body("project", w.a.world.root1), relocate=relocated(w), undo=True,
                         workdir=tmp_path)
    assert answer["verify"]["ok"] and answer["restore"]["provenance"] == "foreign"
    assert answer["undo"]["result"]["state"] == "undone"
    assert w.b_counts() == {"sessions": 0, "projects": 0}
