
from __future__ import annotations

import asyncio
import copy
import json
from typing import Any, Dict, List

from src.core.event_hub import EventHub
from src.core.listing_push.diff import diff, keyed
from src.core.listing_push.publisher import (
    FRAME_TYPE,
    Collection,
    CollectionResult,
    ListingPublisher,
)


def _row(i: int) -> Dict[str, Any]:
    return {
        "activity_status": "idle",
        "unread": False,
        "startup_gate": None,
        "status_source": "registry",
        "tmux_session": f"cloude_s{i}",
        "label": f"session {i}",
        "running_context_used_pct": 12,
        "stats": {"uptime_seconds": 100, "total_commands": 0},
        "session": {
            "id": f"ses_{i}",
            "working_dir": f"/Users/x/project-{i}",
            "pty_pid": 1000 + i,
            "created_at": "2026-09-30T10:00:00",
            "notes": "x" * 800,
        },
    }


class _Rows:

    def __init__(self, n: int) -> None:
        self.rows: List[Dict[str, Any]] = [_row(i) for i in range(n)]

    async def build(self, context: Dict[str, Any]) -> CollectionResult:
        return CollectionResult(rows=copy.deepcopy(self.rows))


def _setup(n: int = 7):
    hub = EventHub()
    source = _Rows(n)
    frames: List[Dict[str, Any]] = []

    def publish(frame: Dict[str, Any]) -> int:
        frames.append(json.loads(json.dumps(frame)))
        return hub.publish(frame)

    publisher = ListingPublisher(
        [Collection("list", source.build, lambda r: r["session"]["id"])],
        publish, lambda: hub.client_count, backstop_seconds=0.05, min_interval=0.0,
    )
    hub.add_listener(publisher.on_hub_publish)
    return hub, source, publisher, frames


def _apply(state: Dict[str, Dict[str, Any]], order: List[str], change: Dict[str, Any]) -> List[str]:
    for up in change.get("upsert", []):
        row = state.setdefault(up["key"], {})
        row.update(up.get("fields", {}))
        for name, part in up.get("nested", {}).items():
            row[name] = {**row.get(name, {}), **part}
        for name in up.get("drop", []):
            row.pop(name, None)
    for key in change.get("remove", []):
        state.pop(key, None)
    return change.get("order", order)


def test_changed_row_is_small_delta_idle_is_silent_and_reconnect_resyncs() -> None:
    async def scenario() -> None:
        hub, source, publisher, frames = _setup()
        hub.register()

        first = await publisher.run_pass()
        assert first is not None and first["type"] == FRAME_TYPE and first["seq"] == 1
        full_bytes = len(json.dumps(first))

        for row in source.rows:
            row["stats"]["uptime_seconds"] += 2
        assert await publisher.run_pass() is None
        assert publisher.seq == 1 and len(frames) == 1

        source.rows[3]["activity_status"] = "working"
        delta = await publisher.run_pass()
        assert delta is not None and delta["seq"] == 2
        change = delta["changes"]["list"]
        assert change == {"upsert": [{"key": "ses_3", "fields": {"activity_status": "working"}}]}
        delta_bytes = len(json.dumps(delta))
        assert delta_bytes < 200 and delta_bytes * 20 < full_bytes

        source.rows[1]["session"]["working_dir"] = "/Users/x/moved"
        nested = (await publisher.run_pass())["changes"]["list"]["upsert"][0]
        assert nested == {"key": "ses_1", "nested": {"session": {"working_dir": "/Users/x/moved"}}}

        source.rows[2]["running_context_used_pct"] = None
        nulled = (await publisher.run_pass())["changes"]["list"]["upsert"][0]
        assert nulled["fields"] == {"running_context_used_pct": None}

        gone = source.rows.pop(0)
        source.rows.append(_row(99))
        moved = (await publisher.run_pass())["changes"]["list"]
        assert moved["remove"] == [gone["session"]["id"]]
        assert moved["upsert"][0]["key"] == "ses_99"
        assert moved["order"][-1] == "ses_99"

        snap = await publisher.snapshot()
        assert snap["stream"] == publisher.stream and snap["seq"] == publisher.seq == len(frames)
        rows = snap["collections"]["list"]["rows"]
        assert [r["session"]["id"] for r in rows] == [r["session"]["id"] for r in source.rows]
        assert snap["collections"]["list"]["ok"] is True

        state: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for frame in frames:
            order = _apply(state, order, frame["changes"]["list"])
        def unclocked(rs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            out = copy.deepcopy(rs)
            for r in out:
                r["stats"].pop("uptime_seconds", None)
            return out

        assert unclocked([state[k] for k in order]) == unclocked(rows)

        task = asyncio.create_task(publisher.run())
        source.rows[0]["unread"] = True
        hub.publish({"type": "session.status"})
        for _ in range(100):
            if publisher.seq > snap["seq"]:
                break
            await asyncio.sleep(0.01)
        assert publisher.seq == snap["seq"] + 1
        task.cancel()

    asyncio.run(scenario())


def test_no_client_means_no_pass() -> None:
    async def scenario() -> None:
        hub, source, publisher, frames = _setup()
        task = asyncio.create_task(publisher.run())
        await asyncio.sleep(0.2)
        task.cancel()
        assert publisher.passes == 0 and frames == []
        snap = await publisher.snapshot()
        assert len(snap["collections"]["list"]["rows"]) == len(source.rows)

    asyncio.run(scenario())


def test_failed_collection_is_a_named_state() -> None:
    async def scenario() -> None:
        hub = EventHub()
        frames: List[Dict[str, Any]] = []

        async def failing(context: Dict[str, Any]) -> CollectionResult:
            return CollectionResult(ok=False, status=503, detail={"listing_reason": "probe_error"})

        publisher = ListingPublisher([Collection("attachable", failing, lambda r: r.get("name"))],
                                     frames.append, lambda: 1)
        frame = await publisher.run_pass()
        assert frame["changes"]["attachable"]["status"]["ok"] is False
        assert frame["changes"]["attachable"]["status"]["status"] == 503
        assert await publisher.run_pass() is None

    asyncio.run(scenario())


def test_diff_keys_drop_repeats_and_keyless_rows() -> None:
    rows = keyed([{"k": "a"}, {"k": None}, {"k": "a", "x": 1}, {"k": "b"}], lambda r: r.get("k"))
    assert [k for k, _ in rows] == ["a", "b"]
    assert diff(rows, rows) is None


def test_snapshot_accepts_a_caller_chosen_age_without_forcing_a_pass() -> None:
    async def scenario() -> None:
        _hub, _source, publisher, _frames = _setup()
        await publisher.run_pass()
        passes = publisher.passes
        publisher._computed_at -= 10.0
        await publisher.snapshot(max_age=30.0)
        assert publisher.passes == passes, "an accepted-age snapshot ran a pass"
        await publisher.snapshot()
        assert publisher.passes == passes + 1, "the default age must still refresh"

    asyncio.run(scenario())
