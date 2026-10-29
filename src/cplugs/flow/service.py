
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from src.cplugs.flow import build, feed, live, store, tail
from src.cplugs.flow.views.page import render_html
from src.cplugs.flow.participants import SEED_KINDS, SeedNotFound
from src.cplugs.sdk import ActivityUnavailable, CplugContext, scrub

SETTLE_S = 300.0
FULL_BLOCKS_MAX = 2000

__all__ = ["SEED_KINDS", "SeedNotFound", "ActivityUnavailable", "get_run", "get_feed", "summarize", "as_page"]


async def get_run(ctx: CplugContext, seed_kind: str, seed_id: str, *, start: Optional[float] = None, end: Optional[float] = None,
                  refresh: bool = False) -> Dict[str, Any]:
    key = store.snapshot_key(seed_kind, str(seed_id), start, end)
    if not refresh:
        held = await asyncio.to_thread(store.load, ctx.storage, key, build.SCHEMA_VERSION)
        if held is not None and held["built_at"] >= held["window"]["end"] + SETTLE_S:
            held["snapshot"] = {"built_at": held.pop("built_at"), "cached": True}
            return held
    now = time.time()
    run = await asyncio.to_thread(build.build_run, ctx.activity, seed_kind, str(seed_id), start=start, end=end, now=now)
    await asyncio.to_thread(store.save, ctx.storage, key, run, now, build.SCHEMA_VERSION)
    run["snapshot"] = {"built_at": now, "cached": False}
    return run


def summarize(run: Dict[str, Any], full: bool = False) -> Dict[str, Any]:
    out = {k: v for k, v in run.items() if k not in ("blocks", "events", "says", "calls")}
    if full:
        out["blocks"] = run["blocks"][:FULL_BLOCKS_MAX]
        out["events"] = run["events"]
        out["says"] = run.get("says", [])
        out["calls"] = run.get("calls", [])
        out["blocks_truncated"] = len(run["blocks"]) > FULL_BLOCKS_MAX
    else:
        counts: Dict[str, int] = {}
        for b in run["blocks"]:
            counts[b["lane"]] = counts.get(b["lane"], 0) + 1
        out["block_counts"] = counts
    return out


def as_page(run: Dict[str, Any]) -> Dict[str, Any]:
    text = render_html(run)
    return {"html": text, "bytes": len(text.encode("utf-8")), "seed": run["seed"], "stats": run["stats"]}


async def get_feed(ctx: CplugContext, seed_kind: str, seed_id: str, *, start: Optional[float] = None,
                   cursor: Optional[float] = None) -> Dict[str, Any]:
    run = await asyncio.to_thread(build.build_run, ctx.activity, seed_kind, str(seed_id), start=start, now=time.time(),
                                  scan=tail.CACHE.scan)
    answer = feed.page(run, cursor)
    answer["items"] = scrub(answer["items"])
    keys = [k for lane in run["lanes"] for k in (lane.get("app_id"), lane.get("tmux_name"))]
    live.WATCH.take(lambda: ctx.notify(live.TOPIC), keys)
    return answer
