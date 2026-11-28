
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.pack.jobs import place
from src.core.pack.jobs.types import PlaceAnswer
from src.core.pack.placement import enhanced, needs as needs_mod
from src.core.pack.placement.needs import Need
from src.core.pack.placement.workload import Workload

logger = structlog.get_logger()

TIMEOUT_S = 3.0
CACHE_TTL_S = 600.0
MAX_OFFERED = 8
WORDS = (*needs_mod.TOOLS, "xcode", "ios_sim", "gpu", "gpu:nvidia", "gpu:amd", "gpu:apple")
PROGRAM_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
CACHE_MAX = 256
_cache: Dict[Tuple[Any, ...], Tuple[float, List[str]]] = {}


def programs_of(command: str) -> List[str]:
    try:
        segments = needs_mod._segments(str(command))
    except ValueError:
        return []
    names = (name for words in segments for name in needs_mod._programs(words))
    return list(dict.fromkeys(n for n in names if PROGRAM_NAME.fullmatch(n)))[:8]


def _enhanced_settings() -> Optional[Any]:
    from src.core.pack.machines import runtime as machines_runtime

    wired = machines_runtime.wiring()
    if wired is None:
        return None
    settings = wired.runtime.operating_settings()
    return settings if settings.placement_mode == "enhanced" else None


async def suggest(kind: str, programs: List[str], offered: List[str], *, decide: Optional[enhanced.DecideFn] = None, timeout: float = TIMEOUT_S,
                  settings: Any = None, clock: Callable[[], float] = time.monotonic) -> List[Need]:
    offered = [w for w in dict.fromkeys(offered) if w in WORDS][:MAX_OFFERED]
    settings = settings if settings is not None else _enhanced_settings()
    if not offered or settings is None or getattr(settings, "placement_mode", None) != "enhanced":
        return []
    key = (kind, tuple(programs), tuple(offered))
    hit = _cache.get(key)
    if hit is not None and clock() - hit[0] < CACHE_TTL_S:
        return [needs_mod.parse_need(w) for w in hit[1]]
    ref: Any = enhanced.FEATURE_ID
    try:
        if decide is None:
            from src.core.byoai import gateway

            gw = gateway.get_gateway()
            decide = gw.decide
            ref = enhanced.target_for(gw, settings.placement_model.model_dump() if getattr(settings, "placement_model", None) else None)
        questions = {f"w{i}": {"type": "choice", "options": ["yes", "no"], "question": f"would a {kind} job running {', '.join(programs) or 'a shell command'} run better on a computer that has {w}?"}
                     for i, w in enumerate(offered)}
        result = await asyncio.wait_for(decide(ref, state={"kind": kind, "programs": programs}, questions=questions), timeout)
    except asyncio.TimeoutError:
        logger.info("pack_needs_model_timeout")
        return []
    except Exception as exc:  # noqa: BLE001
        logger.info("pack_needs_model_fallback", error=type(exc).__name__)
        return []
    answers = getattr(result, "answers", None) or {}
    picked: List[str] = []
    for i, word in enumerate(offered):
        got = answers.get(f"w{i}")
        if (got.get("value") if isinstance(got, dict) else got) == "yes":
            picked.append(word)
    if len(_cache) >= CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (clock(), picked)
    return [needs_mod.parse_need(w) for w in picked]


def _offered(answer: PlaceAnswer, view: place.PlaceView, asked: Sequence[Need]) -> List[str]:
    ids = {r["install_id"] for r in answer.why if r.get("candidate")}
    snaps = [p.snapshot for p in view.peers if p.install_id in ids]
    if len(snaps) < 2:
        return []
    skip = {n.text for n in asked}
    out: List[str] = []
    for word in WORDS:
        if word in skip:
            continue
        got = {needs_mod.meets(s, needs_mod.parse_need(word)) is True for s in snaps}
        if got == {True, False}:
            out.append(word)
    return out


async def refine(answer: PlaceAnswer, work: Workload, uid: str, pol: Any, view: place.PlaceView, ask: Dict[str, Any], kind: str, command: str,
                 *, decide: Optional[enhanced.DecideFn] = None, settings: Any = None) -> PlaceAnswer:
    if answer.decision != "remote":
        return answer
    offered = _offered(answer, view, [*ask.get("needs", ()), *ask.get("filters", ()), *ask.get("prefer", ())])
    if not offered:
        return answer
    wanted = await suggest(kind, programs_of(command), offered, decide=decide, settings=settings)
    if not wanted:
        return answer
    again = place.place(work, uid, pol, view, **{**ask, "prefer": tuple(dict.fromkeys([*ask.get("prefer", ()), *wanted]))})
    return again if again.decision == "remote" else answer
