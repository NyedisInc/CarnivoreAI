"""The serve side of the member-link cost (P20 slice 5d-2b-2b, ``docs/pack-mesh.md`` "Cost of member links"): THIS computer sending its own listing.

``mesh_session_cost.py --mode serve`` spawns this file as one child with an isolated state folder. It builds a real ``PeerListingFeed`` and a real
``EventHub``, registers K member sockets' streams (4 MiB hub bound, 2 MiB frame cap, as ``events_routes`` does for a MeshGrant), drains each in its
own task, and every 2 s moves the view the way a busy owner does (one row flips) and calls ``on_hub_publish(LISTING_DELTA)``.

WHAT THIS IS NOT. The view is SYNTHETIC (``build_rows``, no database, no ``peer_listing.for_caller``, no tmux, no network), so the real view-building
cost is excluded; the CPU figure is the whole process (driver, view and K drain tasks included), an over-count of the feed alone. Both are stated
beside the rows in the table. After a 10 s warm-up it records for ``idle_seconds``: CPU, the 50 ms loop drift, frames, bytes and full frames per socket.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "scripts" / "perf")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

WARMUP_SECONDS = 10.0
FLIP_SECONDS = 2.0


async def drain(stream: Any, counts: Dict[str, Any], index: int) -> None:
    while True:
        text = await stream.get()
        if text is None:
            return
        if counts["armed"]:
            counts["frames"][index] += 1
            counts["bytes"] += len(text)
            if '"full": true' in text[:200]:
                counts["full"][index] += 1


async def run(plan: Dict[str, Any]) -> Dict[str, Any]:
    from mesh_cost_roles import _cpu_seconds, build_rows, refuse_live_tmux, summary
    from perf_client import sample_process
    from src.core.event_hub import EventHub
    from src.core.federation import peer_listing_feed as feed_mod
    from src.core.pack.machines import capabilities
    from src.models import WSMessageType

    refuse_live_tmux()
    capabilities.MESH_BUILD_ON = True
    peers, rows_n, seconds = int(plan["peers"]), int(plan["rows"]), float(plan["idle_seconds"])
    rows, flips = build_rows("mc-serve", rows_n), [0]

    async def view() -> Any:
        flips[0] += 1
        out = [dict(r) for r in rows]
        out[0]["activity_status"] = "working" if flips[0] % 2 else "idle"
        return out, []

    feed = feed_mod.PeerListingFeed(view)
    hub = EventHub()
    counts: Dict[str, Any] = {"armed": False, "frames": [0] * peers, "full": [0] * peers, "bytes": 0}
    clients = [hub.register(reduced=True, max_bytes=feed_mod.MESH_QUEUE_BYTES) for _ in range(peers)]
    drains = [asyncio.create_task(drain(c.stream, counts, i)) for i, c in enumerate(clients)]
    for c in clients:
        await feed.attach(c.stream, cap=feed_mod.MESH_FRAME_BYTES)
    drifts: List[float] = []

    async def monitor() -> None:
        while True:
            t0 = time.perf_counter()
            await asyncio.sleep(0.05)
            if counts["armed"]:
                drifts.append((time.perf_counter() - t0 - 0.05) * 1000)

    async def driver() -> None:
        while True:
            feed.on_hub_publish(WSMessageType.LISTING_DELTA.value)
            await asyncio.sleep(FLIP_SECONDS)

    tasks = [asyncio.create_task(monitor()), asyncio.create_task(driver())]
    rss: List[int] = []
    try:
        await asyncio.sleep(WARMUP_SECONDS)
        attached = len(feed._streams)
        counts["armed"] = True
        c0, t0, last = _cpu_seconds(), time.perf_counter(), 0.0
        while time.perf_counter() - t0 < seconds:
            if time.perf_counter() - last >= 10.0:
                got = await asyncio.to_thread(sample_process, os.getpid())
                if got is not None:
                    rss.append(got.rss_kb)
                last = time.perf_counter()
            await asyncio.sleep(0.5)
        cpu = 100.0 * (_cpu_seconds() - c0) / (time.perf_counter() - t0)
        counts["armed"] = False
        return {"peers": peers, "rows": rows_n, "idle_seconds": seconds, "cpu_pct": cpu, "drift": summary(drifts), "frames": counts["frames"], "full_frames": counts["full"],
                "bytes": counts["bytes"], "attached": attached, "streams_end": len(feed._streams), "rss_kb_max": max(rss) if rss else None,
                "view": "synthetic (build_rows, no database); cpu is the whole process"}
    finally:
        for task in tasks + drains:
            task.cancel()
        for c in clients:
            feed.detach(c.stream)
            hub.unregister(c)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text())
    result = asyncio.run(run(plan))
    out = Path(plan["root"]) / "serve_result.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(result))
    tmp.replace(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
