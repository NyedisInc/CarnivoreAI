
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.byoai import decide as decide_module, registry
from src.core.byoai.contracts import CAP_DECIDE, ByoaiError, NotConfigured, Target

logger = structlog.get_logger()

FEATURE_ID = "pack.placement"
LABEL_KEY = "ai.feature.pack_placement"
DESCRIPTION_KEY = "ai.feature.pack_placement.description"
FEATURE_GROUP = "pack"
TIMEOUT_SECONDS = 3.0

DecideFn = Callable[..., Awaitable[Any]]


class Unavailable(Exception):
    pass


def register_feature() -> None:
    if registry.get_feature(FEATURE_ID) is None:
        registry.register_feature(FEATURE_ID, CAP_DECIDE, LABEL_KEY, DESCRIPTION_KEY, group=FEATURE_GROUP)


def haiku_default(gateway: Any) -> Optional[Target]:
    try:
        for item in gateway.store.read().connections:
            if not item.enabled:
                continue
            names = [*item.models, *(m for m in _preset_models(item.preset))]
            for name in names:
                if "haiku" in name.lower() and getattr(item.models.get(name), "enabled", None) is not False:
                    return gateway.target(item.id, name)
    except (ByoaiError, OSError, ValueError) as exc:
        logger.info("pack_placement_haiku_default_failed", error=type(exc).__name__)
    return None


def _preset_models(preset_id: str) -> List[str]:
    from src.core.byoai.presets import get_preset

    try:
        return list(get_preset(preset_id).default_models)
    except (KeyError, ValueError, AttributeError):
        return []


def target_for(gateway: Any, placement_model: Optional[Dict[str, Any]]) -> Any:
    if placement_model:
        return gateway.target(placement_model["connection"], placement_model["model"])
    block = gateway.store.read()
    if block.features.get(FEATURE_ID) or block.defaults.get(CAP_DECIDE) or block.defaults.get("chat"):
        return FEATURE_ID
    found = haiku_default(gateway)
    if found is None:
        raise NotConfigured("no model is chosen for pack.placement and no Haiku-class model is connected")
    return found


def _labels(candidates: List[Dict[str, Any]]) -> Dict[str, str]:
    seen: Dict[str, str] = {}
    for row in candidates:
        label = row["label"] or row["install_id"][:8]
        n, option = 1, label
        while option in seen:
            n += 1
            option = f"{label} ({n})"
        seen[option] = row["install_id"]
    return seen


async def choose(candidates: List[Dict[str, Any]], workload: Dict[str, Any], *, decide: DecideFn, ref: Any,
                 home_label: Optional[str] = None, timeout: float = TIMEOUT_SECONDS) -> str:
    options = _labels(candidates)
    state = {"job": workload, "home": home_label,
             "machines": [{"machine": option, "cpu_cores_free_after_reserve": row.get("cpu_headroom"),
                           "memory_gb_free_after_reserve": row.get("mem_headroom_gb"), "reserve": row.get("reserve")}
                          for option, row in zip(options, candidates)]}
    questions = {"machine": decide_module.choice(list(options), "which machine should run this job?"),
                 "why": {"type": "choice", "options": ["headroom", "home", "load", "other"], "question": "main reason"}}
    try:
        result = await asyncio.wait_for(decide(ref, state=state, questions=questions), timeout)
    except asyncio.TimeoutError:
        raise Unavailable(f"model did not answer in {timeout:g} s") from None
    except NotConfigured as exc:
        raise Unavailable(f"no model is set up ({exc})") from None
    except ByoaiError as exc:
        raise Unavailable(f"model error ({type(exc).__name__})") from None
    answer = (getattr(result, "answers", None) or {}).get("machine")
    value = answer.get("value") if isinstance(answer, dict) else answer
    if value not in options:
        raise Unavailable("model answered outside the machines offered")
    return options[value]
