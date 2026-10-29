
from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.flow_data import feed as feed_view, live, tail
from src.core.flow_data.collect import build
from src.core.flow_data.collect.participants import SEED_KINDS, SeedNotFound
from src.cplugs.host import frame_serving
from src.cplugs.host.activity_reader import ActivityReader
from src.cplugs.runtime import guards
from src.cplugs.sdk import ActivityUnavailable, scrub

INLINE_MAX = 512 * 1024
PART_BUDGET = 640 * 1024
MAX_CONCURRENT_BUILDS = 2
_BUILDS = asyncio.Semaphore(MAX_CONCURRENT_BUILDS)
HARD_MAX = 32 * 1024 * 1024
CACHE_ENTRIES = 3
CACHE_TTL_S = 600.0
DROPPED_KEYS = ("says", "calls", "snapshot")
MAX_ID_CHARS = 200
TASKS_DEFAULT, TASKS_MAX, TASKS_QUERY_MAX, TITLE_MAX = 30, 100, 200, 120
DEFAULT_SEED = "huddle_item"


def _number(params: Dict[str, Any], key: str) -> Optional[float]:
    value = params.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise guards.Refused("invalid_params", f"{key} must be epoch seconds")
    return float(value)


def parse_params(params: Dict[str, Any]) -> Dict[str, Any]:
    seed = params.get("seed", DEFAULT_SEED)
    if seed not in SEED_KINDS:
        raise guards.Refused("invalid_params", f"seed must be one of {sorted(SEED_KINDS)}")
    ident = params.get("id")
    if not isinstance(ident, str) or not ident or len(ident) > MAX_ID_CHARS:
        raise guards.Refused("invalid_params", "id must be non-empty text")
    if not isinstance(params.get("refresh", False), bool):
        raise guards.Refused("invalid_params", "refresh must be true or false")
    return {"seed": seed, "id": ident, "start": _number(params, "start"), "end": _number(params, "end")}


def serialize(run: Dict[str, Any]) -> str:
    text = json.dumps(run, separators=(",", ":"), ensure_ascii=True)
    if len(text) > HARD_MAX:
        raise guards.Refused("too_large", "the run is over the hard cap; ask for a narrower window", {"bytes": len(text), "limit": HARD_MAX})
    return text


def build_checked(activity: Any, params: Dict[str, Any], now: Optional[float] = None, **kw: Any) -> Dict[str, Any]:
    at = time.time() if now is None else now
    try:
        return build.build_run(activity, params["seed"], params["id"], start=params["start"], end=params.get("end"), now=at, **kw)
    except SeedNotFound as exc:
        raise guards.Refused("not_found", str(exc)[:200]) from exc
    except ValueError as exc:
        raise guards.Refused("invalid_params", str(exc)[:200]) from exc
    except ActivityUnavailable as exc:
        raise guards.Refused("unavailable", str(exc)[:200]) from exc


def build_scrubbed(activity: Any, params: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    run = build_checked(activity, params, now)
    for key in DROPPED_KEYS:
        run.pop(key, None)
    return scrub(run)


def cut_parts(text: str) -> List[str]:
    parts: List[str] = []
    pos = 0
    while pos < len(text) or not parts:
        chunk = text[pos:pos + PART_BUDGET]
        encoded = len(json.dumps(chunk))
        while encoded > PART_BUDGET:
            chunk = chunk[:max(1, len(chunk) - (encoded - PART_BUDGET))]
            encoded = len(json.dumps(chunk))
        parts.append(chunk)
        pos += len(chunk)
    return parts


def parse_tasks_params(params: Dict[str, Any]) -> Tuple[str, int]:
    query = params.get("query", "")
    if query is None:
        query = ""
    if not isinstance(query, str) or len(query) > TASKS_QUERY_MAX:
        raise guards.Refused("invalid_params", f"query must be text of at most {TASKS_QUERY_MAX} characters")
    limit = params.get("limit")
    if limit is None:
        limit = TASKS_DEFAULT
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise guards.Refused("invalid_params", "limit must be a whole number")
    return query.strip(), max(1, min(TASKS_MAX, limit))


def task_row(row: Dict[str, Any]) -> Dict[str, Any]:
    first = next((ln.strip() for ln in (row.get("text") or "").splitlines() if ln.strip()), "")
    title = (row.get("title") or "").strip() or first
    return {"id": row["id"], "number": None, "title": title[:TITLE_MAX], "state": row.get("state") or "",
            "list": row.get("list_key") or "", "updated": float(row.get("updated_at") or 0)}


class PartCache:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._held: Dict[str, "OrderedDict[str, Tuple[float, List[str]]]"] = {}

    def put(self, install_key: str, parts: List[str]) -> str:
        self._sweep()
        entries = self._held.setdefault(install_key, OrderedDict())
        token = secrets.token_urlsafe(16)
        entries[token] = (self._clock() + CACHE_TTL_S, parts)
        while len(entries) > CACHE_ENTRIES:
            entries.popitem(last=False)
        return token

    def get(self, install_key: str, token: object) -> Optional[List[str]]:
        self._sweep()
        found = self._held.get(install_key, {}).get(token) if isinstance(token, str) else None
        return found[1] if found else None

    def forget(self, install_key: str) -> None:
        self._held.pop(install_key, None)

    def _sweep(self) -> None:
        now = self._clock()
        for key in list(self._held):
            entries = self._held[key]
            for token in [t for t, (until, _) in entries.items() if until <= now]:
                del entries[token]
            if not entries:
                del self._held[key]


class FlowPort:

    def __init__(self, state_dir: Callable[[], Path], reader: Callable[[Path], Any] = ActivityReader,
                 cache: Optional[PartCache] = None, on_topic: Optional[Callable[[str, str], None]] = None,
                 serving: Callable[[str], bool] = frame_serving.is_serving) -> None:
        self._state_dir, self._reader, self.cache, self._on_topic, self._serving = state_dir, reader, cache or PartCache(), on_topic, serving

    def _run_text(self, params: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        run = build_scrubbed(self._reader(self._state_dir()), parse_params(params))
        return run, serialize(run)

    async def run(self, install_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        async with _BUILDS:
            run, text = await asyncio.to_thread(self._run_text, params)
        if len(text) <= INLINE_MAX:
            return {"run": run}
        parts = await asyncio.to_thread(cut_parts, text)
        return {"token": self.cache.put(install_key, parts), "parts": len(parts), "bytes": len(text)}

    def _tasks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query, limit = parse_tasks_params(params)
        try:
            rows = self._reader(self._state_dir()).task_manager_recent(query, limit)
        except ActivityUnavailable as exc:
            raise guards.Refused("unavailable", str(exc)[:200]) from exc
        except sqlite3.Error as exc:
            raise guards.Refused("unavailable", f"the task store cannot be read: {exc}"[:200]) from exc
        return scrub({"tasks": [task_row(r) for r in rows]})

    async def tasks(self, install_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.to_thread(self._tasks, params)

    async def part(self, install_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        parts = self.cache.get(install_key, params.get("token"))
        if parts is None:
            raise guards.Refused("not_found", "unknown or expired token")
        index = params.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(parts):
            raise guards.Refused("invalid_params", f"index must be 0 to {len(parts) - 1}")
        return {"index": index, "text": parts[index]}

    def _feed_page(self, params: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        run = build_checked(self._reader(self._state_dir()), params, scan=tail.CACHE.scan)
        answer = feed_view.page(run, params["cursor"])
        answer["items"] = scrub(answer["items"])
        return answer, [k for lane in run["lanes"] for k in (lane.get("app_id"), lane.get("tmux_name")) if k]

    async def feed(self, install_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._serving(install_key):
            raise guards.Refused("unavailable", "flow.feed answers only while a page frame's route call is open", {"reason": "no_frame_open"})
        parsed = parse_params(params)
        cursor = _number(params, "cursor")
        topic = params.get("topic")
        if not isinstance(topic, str) or self._on_topic is None:
            raise guards.Refused("unavailable", "flow.feed needs a declared topic")
        async with _BUILDS:
            answer, keys = await asyncio.to_thread(self._feed_page, {**parsed, "cursor": cursor})
        on_topic = self._on_topic
        live.watch_for(f"{install_key}:{topic}").take(lambda: on_topic(install_key, topic), keys)
        return answer
