
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.db_reuse.change_cache import CACHE
from src.core.resource_push import notifier as notifier_module
from src.core.work.storage import WorkStorage
from src.cplugs.huddle import push_delta
from src.cplugs.sdk import CplugContext

ITEMS = 40


class _Projects:

    def list(self, **_kwargs: Any) -> List[Dict[str, Any]]:
        return [{"id": 1, "name": "one"}, {"id": 2, "name": "two"}]


def _ctx(tmp_path: Path) -> CplugContext:
    storage = WorkStorage(tmp_path / "cplugs" / "huddle", tmp_path)
    return CplugContext("huddle", storage=storage, settings={}, notify=lambda name, key=None: None, log=None,
                        grants=frozenset(), capabilities={"projects": _Projects()})


@pytest.fixture()
def rig(tmp_path: Path):
    CACHE.clear()
    ctx = _ctx(tmp_path)
    store = push_delta.service.store(ctx)
    ids = [store.add(("all", "1", "2")[n % 3], f"item {n}", actor="joe")["id"] for n in range(ITEMS)]
    store.post(ids[0], "a first note", actor="claude", kind="info")
    frames: List[Dict[str, Any]] = []
    publisher = push_delta.DeltaPublisher(ctx, publish=lambda data: frames.append(data) or True)
    yield store, ids, publisher, frames
    publisher.close()
    CACHE.clear()


def test_one_edit_is_one_frame_with_only_that_item(rig):
    store, ids, publisher, frames = rig

    async def run() -> None:
        publisher.start()
        await publisher.idle()
        assert frames == []
        before = publisher.marker()["delta_seq"]
        store.update(ids[3], actor="joe", text="edited once")
        publisher.on_topics(["cplug.huddle.list:all"])
        await publisher.idle()
        assert len(frames) == 1
        frame = frames[0]
        assert frame["seq"] == before + 1 == publisher.marker()["delta_seq"]
        assert frame["epoch"] == publisher.marker()["delta_epoch"]
        assert [entry["list"] for entry in frame["lists"]] == ["all"]
        entry = frame["lists"][0]
        assert [item["id"] for item in entry["items"]] == [ids[3]]
        assert entry["items"][0]["text"] == "edited once" and entry["items"][0]["thread_slim"] is True
        assert entry["deleted"] == [] and ids[3] in entry["order"] and str(ids[3]) in entry["numbers"]
        print(f"one edit: 1 frame, {len(entry['items'])} row of {len(entry['order'])} in the list, "
              f"{len(json.dumps(frame))} bytes (before: every window re-read /lists and the whole list)")

        publisher.on_topics(["cplug.huddle.list:all"])
        await publisher.idle()
        assert len(frames) == 1

        store.delete(ids[6], actor="joe")
        store.move(ids[1], "2", actor="joe")
        publisher.on_topics(["cplug.huddle.list:all", "cplug.huddle.list:1", "cplug.huddle.list:2"])
        await publisher.idle()
        assert len(frames) == 2
        by_list = {e["list"]: e for e in frames[1]["lists"]}
        assert by_list["all"]["deleted"] == [ids[6]]
        assert by_list["1"]["deleted"] == [ids[1]] and [i["id"] for i in by_list["2"]["items"]] == [ids[1]]

    asyncio.run(run())


def test_a_burst_over_the_bound_is_one_resync(rig, monkeypatch):
    store, ids, publisher, frames = rig
    monkeypatch.setattr(push_delta, "MAX_ITEMS", 5)

    async def run() -> None:
        publisher.start()
        await publisher.idle()
        for item_id in ids[:9]:
            store.update(item_id, actor="joe", note="bulk")
        publisher.on_topics(["cplug.huddle.list:all", "cplug.huddle.list:1", "cplug.huddle.list:2"])
        await publisher.idle()
        assert len(frames) == 1 and frames[0]["resync"] is True and "lists" not in frames[0]

    asyncio.run(run())


def test_the_plugin_follows_its_family_and_pushes_a_data_frame():
    published: List[Dict[str, Any]] = []
    heard: List[List[str]] = []

    async def run() -> None:
        notifier_module.install(lambda frame: published.append(frame) or 1, window_seconds=60)
        remove = notifier_module.add_family_listener("cplug.huddle.list", heard.append)
        try:
            notifier_module.notify("cplug.huddle.list:12")
            notifier_module.notify("layouts")
            notifier_module._active.flush()
            assert heard == [["cplug.huddle.list:12"]]
            assert notifier_module.publish_frame({"type": "cplug.data", "topic": "cplug.huddle.delta", "data": {"seq": 1}})
            assert published[-1]["type"] == "cplug.data"
        finally:
            remove()
            notifier_module.uninstall()
        assert not notifier_module.publish_frame({"type": "cplug.data"})

    asyncio.run(run())


def _complete(store: Any, item_ids: List[int]) -> None:
    for item_id in item_ids:
        store.update(item_id, actor="joe", approve=True)
    marks = ",".join("?" * len(item_ids))
    with closing(store._connect(True)) as conn, conn:
        conn.execute(f"UPDATE work_items SET claude_read_seq = joe_seq WHERE id IN ({marks})", item_ids)


def test_a_list_with_done_items_sends_live_rows_only(rig):
    store, ids, publisher, frames = rig
    done = [ids[n] for n in range(0, ITEMS, 3)][1:5]
    _complete(store, done)

    async def run() -> None:
        publisher.start()
        await publisher.idle()
        store.update(ids[3 * 7], actor="joe", text="edited")
        publisher.on_topics(["cplug.huddle.list:all"])
        await publisher.idle()
        entry = frames[-1]["lists"][0]
        assert not set(done) & set(entry["order"]), "a completed id in order makes a live-only window re-read the whole list"
        assert not {str(i) for i in done} & set(entry["numbers"])
        assert entry["done_count"] == len(done) and entry["done_swarm"] == 0
        assert [i["id"] for i in entry["items"]] == [ids[21]]

        _complete(store, [ids[21]])
        publisher.on_topics(["cplug.huddle.list:all"])
        await publisher.idle()
        entry = frames[-1]["lists"][0]
        assert entry["deleted"] == [ids[21]] and ids[21] not in entry["order"]
        assert [(i["id"], i["state"]) for i in entry["items"]] == [(ids[21], "done")]
        assert entry["done_count"] == len(done) + 1
        print(f"live-only frame: order {len(entry['order'])} live ids, done_count {entry['done_count']}")

    asyncio.run(run())
