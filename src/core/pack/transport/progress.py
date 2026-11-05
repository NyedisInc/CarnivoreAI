
from __future__ import annotations

import os
import time
from collections import OrderedDict, deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Mapping, Optional, Tuple

LOG_LINES = 200
KEEP_OPS = 24
RATE_WINDOW = 10.0
RATE_MIN_SPAN = 2.0
PUSH_EVERY = 1.0


@dataclass
class Track:

    step: Optional[str] = None
    done: int = 0
    total: int = 0
    samples: Deque[Tuple[float, int]] = field(default_factory=deque)
    log: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=LOG_LINES))


_tracks: "OrderedDict[str, Track]" = OrderedDict()
_bound: ContextVar[Optional[str]] = ContextVar("pack_progress_op", default=None)


def _track(op_id: str) -> Track:
    track = _tracks.get(op_id)
    if track is None:
        track = _tracks[op_id] = Track()
        while len(_tracks) > KEEP_OPS:
            _tracks.popitem(last=False)
    return track


def _push(op_id: str, *, now: bool = True) -> None:
    from src.core import resource_push
    from src.core.resource_push import topics

    for topic in (topics.keyed(topics.PACK_OPS, op_id), topics.PACK_OPS):
        if now:
            resource_push.notify(topic)
        else:
            resource_push.notify_coalesced(topic, "progress:" + topic, PUSH_EVERY)


def plain(text: str) -> str:
    home = os.path.expanduser("~")
    return " ".join(text.replace(home, "~").split())[:240]


def _line(op_id: str, track: Track, text: str, *, push: bool = True) -> None:
    track.log.append({"at": time.time(), "step": track.step, "text": plain(text)})
    if push:
        _push(op_id)


def log(op_id: str, text: str) -> None:
    _line(op_id, _track(op_id), text)


def bind(op_id: str) -> None:
    _track(op_id)
    _bound.set(op_id)


def on_update(op_id: str, role: str, *, state: Optional[str], step: Optional[str], error_code: Optional[str], detail: Optional[Mapping[str, Any]]) -> None:
    if role != "source":
        return
    track = _track(op_id)
    if step and step != track.step:
        track.step, track.done, track.total = step, 0, 0
        track.samples.clear()
        _line(op_id, track, f"step {step} started", push=False)
    if state:
        _line(op_id, track, f"state {state}", push=False)
    error = (detail or {}).get("error")
    if error_code or isinstance(error, str):
        _line(op_id, track, "error " + " ".join(x for x in (error_code, error if isinstance(error, str) else None) if x), push=False)


def blob_start(kind: str, size: int, already: int) -> None:
    op_id = _bound.get()
    if op_id is None:
        return
    track = _track(op_id)
    track.total += size
    track.done += already
    _line(op_id, track, f"sending {kind}: {size} bytes" + (f", {already} already there" if already else ""))


def blob_bytes(count: int) -> None:
    op_id = _bound.get()
    if op_id is None:
        return
    track = _track(op_id)
    track.done += count
    now = time.monotonic()
    track.samples.append((now, track.done))
    while track.samples and now - track.samples[0][0] > RATE_WINDOW:
        track.samples.popleft()
    _push(op_id, now=False)


def blob_sealed(kind: str, size: int) -> None:
    op_id = _bound.get()
    if op_id is not None:
        _line(op_id, _track(op_id), f"the other computer verified the {kind} file ({size} bytes)")


def view(op_id: str) -> Optional[Dict[str, Any]]:
    track = _tracks.get(op_id)
    if track is None:
        return None
    rate = eta = None
    if len(track.samples) >= 2:
        (t0, d0), (t1, d1) = track.samples[0], track.samples[-1]
        if t1 - t0 >= RATE_MIN_SPAN and d1 > d0:
            rate = (d1 - d0) / (t1 - t0)
            eta = round((track.total - track.done) / rate) if track.total > track.done else None
    log_out: List[Dict[str, Any]] = list(track.log)
    return {"step": track.step, "bytes_done": track.done if track.total else None, "bytes_total": track.total or None,
            "rate": round(rate) if rate else None, "eta_s": eta, "log": log_out}
