
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict

import src.api.session_listing_collections as collections
from src.api.session_listing_collections import build_records, running_join_row
from src.core.ui_preferences_store import UiPreferencesStore

CLOSED = "0f1e2d3c-4b5a-4968-8776-65544332211a"
OTHER = "1a2b3c4d-5e6f-4a0b-9c8d-7e6f5a4b3c2d"
FIELD = "drawer_arrangement"
ARRANGEMENT = {"v": 1, "pinned": [CLOSED, OTHER], "order": [OTHER, CLOSED], "bands": {"rogue": [CLOSED]}, "collapsed": []}


class FakeRecord:

    def __init__(self, uuid: str) -> None:
        self.row: Dict[str, Any] = {"session_uuid": uuid, "closed": True, "lifecycle": "stopped"}

    def model_dump(self, mode: str = "json") -> Dict[str, Any]:
        return dict(self.row)


def test_a_pinned_closed_session_keeps_its_pin_and_is_listed_after_a_records_pass(tmp_path, monkeypatch):
    async def fake_rows(app_state, keep, infos, wake_shared):
        return [FakeRecord(CLOSED)]

    monkeypatch.setattr(collections, "stored_record_rows", fake_rows)
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    store = UiPreferencesStore(lambda: cfg)
    store.update({FIELD: ARRANGEMENT}, store.read()["revision"])
    state = SimpleNamespace(ui_preferences_store=store)

    result = asyncio.run(build_records(state, {}))

    arrangement = store.read()["values"][FIELD]
    assert arrangement["pinned"] == [CLOSED, OTHER]
    assert arrangement["order"] == [OTHER, CLOSED]
    assert arrangement["bands"] == {"rogue": [CLOSED]}
    assert [r["session_uuid"] for r in result.rows] == [CLOSED]
    closed_row = {"lifecycle": "stopped", "lifecycle_source": "closed_by_user", "tmux_created_epoch": 5,
                  "archived_at": None, "tmux_name": "carnivore_x", "claude_session_uuid": None}
    assert running_join_row(closed_row, set()) is True


def test_a_live_peer_job_worker_is_imported_but_an_asleep_one_is_not():
    from src.core.federation import peer_listing
    from src.core.federation.shadow_rows import JOB_WORKER_DIR, usable

    base = {"name": "carnivore_ses_a", "session_uuid": "u", "label": "job 01020304: builder"}
    for folder in ("/Users/demo/.carnivore/jobs/folders/alpha-repo-01020304/slot2", "/Users/demo/.carnivore/jobs/folders/alpha-repo-01020304/slot3/sub"):
        assert usable({**base, "working_dir": folder})
        assert JOB_WORKER_DIR.search(folder)
    assert usable({**base, "working_dir": "/Users/demo/carnivore-projects/host-b"})
    assert not JOB_WORKER_DIR.search("/Users/demo/carnivore-projects/host-b")
    assert "JOB_WORKER_DIR" in open(peer_listing.__file__).read()
