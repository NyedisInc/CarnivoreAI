
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.api import events_routes
from src.api.pack_jobs_routes import _page_view, _parse_cursor
from src.core.event_hub import EventHub
from src.core.pack.jobs.feed import JobsFeed
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import HostJob, HostState, JobRecord, JobState

WINDOW = 0.05


class FakeHub:

    def __init__(self) -> None:
        self.frames: List[Dict[str, Any]] = []

    def publish(self, frame: Dict[str, Any], reduced: Any = None) -> int:
        self.frames.append(frame)
        return 1


def _rig(tmp_path: Path):
    store, hub = JobStore(tmp_path / "state"), FakeHub()
    feed = JobsFeed(hub, store, coalesce_s=WINDOW)
    store.on_change, store.on_removed = feed.changed, feed.removed
    return store, hub, feed


def _job(job_id: str, created: float = 100.0, **kw: Any) -> JobRecord:
    return JobRecord(id=job_id, state=kw.pop("state", JobState.RUNNING), created_at=created, updated_at=created, **kw)


@pytest.mark.asyncio
async def test_a_state_change_sends_one_frame_at_once_and_seq_rises_by_one(tmp_path: Path):
    store, hub, feed = _rig(tmp_path)
    store.create_job(_job("job_a"))
    assert [f["seq"] for f in hub.frames] == [1] and hub.frames[0]["job"]["state"] == "running" and hub.frames[0]["job"]["side"] == "caller"
    store.set_state("job_a", JobState.COLLECTING, note="x")
    assert [f["seq"] for f in hub.frames] == [1, 2] and hub.frames[1]["job"]["state"] == "collecting" and feed.seq() == 2
    await asyncio.sleep(WINDOW * 3)
    assert len(hub.frames) == 2


@pytest.mark.asyncio
async def test_ten_usage_updates_in_the_window_send_one_frame_with_the_last_value(tmp_path: Path):
    store, hub, _ = _rig(tmp_path)
    store.create_job(_job("job_a"))
    hub.frames.clear()
    for n in range(10):
        store.set_state("job_a", JobState.RUNNING, usage_json=json.dumps({"n": n}))
    assert hub.frames == []
    await asyncio.sleep(WINDOW * 4)
    assert len(hub.frames) == 1 and hub.frames[0]["job"]["usage"] == {"n": 9}


@pytest.mark.asyncio
async def test_a_purge_sends_removed_with_the_ids(tmp_path: Path):
    store, hub, _ = _rig(tmp_path)
    store.create_job(_job("job_a"))
    store.set_state("job_a", JobState.DONE)
    hub.frames.clear()
    assert store.purge_before(9e12) == 1
    assert len(hub.frames) == 1 and hub.frames[0]["removed"] == ["job_a"] and "job" not in hub.frames[0]


def test_a_hook_that_raises_does_not_break_set_state(tmp_path: Path):
    store = JobStore(tmp_path / "state")

    def boom(*_: Any) -> None:
        raise RuntimeError("listener bug")

    store.on_change = store.on_removed = boom
    store.create_job(_job("job_a"))
    assert store.set_state("job_a", JobState.DONE).state is JobState.DONE
    assert store.get_job("job_a").state is JobState.DONE and store.purge_before(9e12) == 1


def test_paging_by_before_has_no_repeat_and_no_gap_across_equal_created_at(tmp_path: Path):
    store = JobStore(tmp_path / "state")
    for i, created in enumerate([50.0, 60.0, 60.0, 60.0, 70.0, 70.0, 80.0]):
        store.create_job(_job(f"job_{i}", created))
    store.host_put(HostJob(job_id="host_x", caller_install="peer-1", state=HostState.RUNNING, created_at=60.0))
    store.host_put(HostJob(job_id="warm-abc", caller_install="peer-1", state=HostState.RUNNING, created_at=60.0))
    seen: List[str] = []
    cursor = None
    for _ in range(10):
        page = _page_view(store, store.state_dir, limit=3, live_only=False, before=_parse_cursor(cursor), caller=None, project_uid=None)
        seen += [j["id"] for j in page["jobs"]]
        cursor = page["next_before"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(["job_0", "job_1", "job_2", "job_3", "job_4", "job_5", "job_6", "host_x"])
    assert len(seen) == len(set(seen)) and "warm-abc" not in seen


def test_bad_cursors_are_422(tmp_path: Path):
    for bad in ("", "nope", "1.0", "x|job_a", "nan|job_a", "1.0|", "1.0|a b", "1.0|" + "a" * 81):
        with pytest.raises(Exception) as err:
            _parse_cursor(bad)
        assert getattr(err.value, "status_code", None) == 422, bad
    assert _parse_cursor(None) is None and _parse_cursor("12.5|job_a") == (12.5, "job_a")


def test_caller_and_project_filters_and_host_rows_are_listed_read_only(tmp_path: Path):
    store = JobStore(tmp_path / "state")
    store.create_job(_job("job_a", 10.0, caller_session="uuid-1", project_uid="p1"))
    store.create_job(_job("job_b", 20.0, caller_session="uuid-2", project_uid="p2"))
    store.host_put(HostJob(job_id="host_x", caller_install="peer-1", project_uid="p1", state=HostState.PARKED, created_at=30.0))

    def ids(**q: Any) -> List[str]:
        args = dict(limit=50, live_only=False, before=None, caller=None, project_uid=None) | q
        return [j["id"] for j in _page_view(store, store.state_dir, **args)["jobs"]]

    assert ids() == ["host_x", "job_b", "job_a"]
    assert ids(caller="uuid-1") == ["job_a"]
    assert ids(project_uid="p1") == ["host_x", "job_a"]
    host = _page_view(store, store.state_dir, limit=50, live_only=True, before=None, caller=None, project_uid="p1")["jobs"][0]
    assert host["side"] == "host" and host["computer"] == "peer-1" and host["state"] == "parked" and host["caller_session"] is None


@pytest.mark.asyncio
async def test_a_host_row_is_pushed_with_side_host_and_a_warm_up_row_is_not(tmp_path: Path):
    store, hub, _ = _rig(tmp_path)
    store.host_put(HostJob(job_id="warm-abc", caller_install="peer-1", state=HostState.RUNNING))
    store.host_set("warm-abc", state=HostState.EXITED)
    assert hub.frames == []
    store.host_put(HostJob(job_id="host_x", caller_install="peer-1", state=HostState.PREPARING))
    store.host_set("host_x", state=HostState.RUNNING)
    assert [(f["seq"], f["job"]["side"], f["job"]["state"]) for f in hub.frames] == [(1, "host", "preparing"), (2, "host", "running")]
    store.host_delete("host_x")
    assert hub.frames[-1]["removed"] == ["host_x"]


class FakeSocket:

    def __init__(self) -> None:
        self.sent: List[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


@pytest.mark.asyncio
async def test_no_frame_reaches_a_paired_computers_socket(tmp_path: Path):
    hub = EventHub()
    local, peer = hub.register(), hub.register(reduced=True)
    store = JobStore(tmp_path / "state")
    feed = JobsFeed(hub, store, coalesce_s=WINDOW)
    store.on_change, store.on_removed = feed.changed, feed.removed
    store.create_job(_job("job_a"))
    store.set_state("job_a", JobState.DONE)
    store.purge_before(9e12)
    hub.unregister(local)
    hub.unregister(peer)
    local_sock, peer_sock = FakeSocket(), FakeSocket()
    await events_routes._drain_to_socket(local_sock, local.stream, False)
    await events_routes._drain_to_socket(peer_sock, peer.stream, True)
    assert [json.loads(t)["seq"] for t in local_sock.sent] == [1, 2, 3]
    assert peer_sock.sent == []


def test_the_view_carries_the_uuid_a_listing_row_of_the_worker_has_here(tmp_path: Path):
    from src.core.federation.shadow_rows import shadow_uuid

    store = JobStore(tmp_path / "state")
    store.create_job(_job("job_a", peer_install_id="peer-9", worker_session_uuid="w-1"))
    store.create_job(_job("job_b", 5.0))
    page = {j["id"]: j for j in _page_view(store, store.state_dir, limit=9, live_only=False, before=None, caller=None, project_uid=None)["jobs"]}
    assert page["job_a"]["worker_listing_uuid"] == shadow_uuid("peer-9", "w-1") != "w-1" and page["job_a"]["worker_session_uuid"] == "w-1"
    assert page["job_b"]["worker_listing_uuid"] is None
