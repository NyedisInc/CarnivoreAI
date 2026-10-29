
from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

import structlog

from src.config import settings
from src.core import resource_push, terminal_background
from src.core.byoai import gateway as gateway_module, registry
from src.core.byoai.contracts import CAP_IMAGE, ByoaiError, InvalidKey, LoginExpired, MissingKey, NotConfigured
from src.core.companies import hero_art_prompt, hero_images
from src.core.resource_push import topics as resource_topics
from src.core.skill_manager import ai_job, card_art_crop, card_art_style

logger = structlog.get_logger()

FEATURE_ID = "skills.card_art"
LABEL_KEY = "ai.feature.skills_card_art"
DESCRIPTION_KEY = "ai.feature.skills_card_art.description"
FEATURE_GROUP = "skills"
KIND = "skill"
DIR_NAME = "skill_card_art"
DESCRIPTION_MAX = 300
MAX_JOBS = 3
RETRY_AFTER_SECONDS = 3600
PROCESS_STARTED_AT = time.time()
ATTEMPT_STARTED = "attempt started"
WORKERS = 2
MAX_LOCATIONS = 300
AUTO_GENERATE = True

_pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="skill-art")
_inflight: Set[str] = set()
_lock = threading.Lock()


def register_feature() -> None:
    if registry.get_feature(FEATURE_ID) is None:
        registry.register_feature(FEATURE_ID, CAP_IMAGE, LABEL_KEY, DESCRIPTION_KEY, group=FEATURE_GROUP)


def art_id(harness: str, name: str, location_id: str) -> str:
    return hashlib.sha256(f"{harness}\0{name}\0{location_id}".encode()).hexdigest()[:32]


def store_dir() -> Path:
    return settings.get_state_dir() / DIR_NAME


def find(key: str) -> Optional[Path]:
    if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
        return None
    for ext in terminal_background.CONTENT_TYPES:
        candidate = store_dir() / f"{key}.{ext}"
        if candidate.is_file():
            return candidate
    return None


def _style_path(key: str) -> Path:
    return store_dir() / f"{key}.style"


def is_stale(key: str) -> bool:
    try:
        return _style_path(key).read_text(encoding="utf-8").strip() != str(card_art_style.STYLE_VERSION)
    except OSError:
        return True


def _fail_path(key: str) -> Path:
    return store_dir() / f"{key}.fail.json"


def _read_fail(key: str) -> Dict[str, Any]:
    return ai_job.read_fail(_fail_path(key))


def enabled() -> bool:
    try:
        return gateway_module.get_gateway().store.read().features.get(FEATURE_ID) is not None
    except (ByoaiError, OSError, ValueError) as exc:
        logger.info("skill_card_art_config_unreadable", error=type(exc).__name__)
        return False


def build_prompt(name: str, description: str) -> str:
    shown, about = hero_art_prompt.clean_name(name), " ".join(description.split())[:DESCRIPTION_MAX]
    if not shown or hero_art_prompt.has_secret(name) or hero_art_prompt.has_secret(about):
        raise ValueError("name is empty or the text looks like a secret")
    return card_art_style.build_prompt(KIND, shown, about)


class LinkReply(ValueError):
    pass


def _note(key: str, reason: str, *, final: bool = False, bump: bool = True) -> None:
    prior = int(_read_fail(key).get("attempts", 0))
    attempts = MAX_JOBS if final else (prior + 1 if bump else max(prior, 1))
    ai_job.write_fail(_fail_path(key), attempts, reason, log_event="skill_card_art_note_failed")
    if reason == ATTEMPT_STARTED:
        logger.info("skill_card_art_attempt_started", art_id=key, attempts=attempts)
    else:
        logger.warning("skill_card_art_failed", art_id=key, reason=reason)


def _request_fields(model: Optional[str]) -> Dict[str, Any]:
    fields: Dict[str, Any] = {"n": 1}
    if "gpt-image" in (model or "").lower():
        fields.update(quality="medium", size=card_art_crop.REQUEST_SIZE)
    return fields


async def _make(prompt: str) -> bytes:
    target = gateway_module.get_gateway().feature_target(FEATURE_ID)
    if target is None:
        raise NotConfigured(f"{FEATURE_ID} has no connection chosen")
    result = await gateway_module.generate(target, prompt, _request_fields(getattr(target, "model", None)), capability=CAP_IMAGE,
                                            feature=FEATURE_ID)
    if not result.items:
        raise ValueError("the image server returned no image")
    data = result.items[0].data
    if not data:
        raise LinkReply("the image server returned a link, not an image")
    return data


def generate(key: str, name: str, description: str, *, regenerate: bool = False) -> Dict[str, Any]:
    if not enabled():
        return {"status": "off"}
    if not regenerate and find(key) is not None:
        return {"status": "exists"}
    try:
        prompt = build_prompt(name, description)
    except ValueError as exc:
        _note(key, str(exc), final=True)
        return {"status": "refused", "reason": str(exc)}
    _note(key, ATTEMPT_STARTED)
    try:
        raw = asyncio.run(_make(prompt))
        if terminal_background.sniff_image_extension(raw[: terminal_background.SNIFF_LENGTH]) is None:
            raise ValueError("the image reply is not a supported image")
        raw = card_art_crop.crop_16_9(raw)
        ext = terminal_background.sniff_image_extension(raw[: terminal_background.SNIFF_LENGTH])
        if ext is None:
            raise ValueError("the image reply is not a supported image")
        hero_images.atomic_write(store_dir() / f"{key}.{ext}", raw)
        hero_images.atomic_write(_style_path(key), str(card_art_style.STYLE_VERSION).encode())
        for other in terminal_background.CONTENT_TYPES:
            if other != ext:
                (store_dir() / f"{key}.{other}").unlink(missing_ok=True)
    except (NotConfigured, MissingKey, InvalidKey, LoginExpired) as exc:
        _fail_path(key).unlink(missing_ok=True)
        return {"status": "off", "reason": str(exc)}
    except LinkReply as exc:
        _note(key, str(exc), final=True)
        return {"status": "failed", "reason": type(exc).__name__}
    except (ByoaiError, ValueError, OSError) as exc:
        _note(key, f"{type(exc).__name__}: {str(exc)[:120]}", bump=False)
        return {"status": "failed", "reason": type(exc).__name__}
    except Exception as exc:
        _note(key, f"{type(exc).__name__}: {str(exc)[:120]}", bump=False)
        return {"status": "failed", "reason": type(exc).__name__}
    _fail_path(key).unlink(missing_ok=True)
    resource_push.notify(resource_topics.LOCAL_SKILLS)
    logger.info("skill_card_art_generated", art_id=key)
    return {"status": "generated"}


def _job(key: str, name: str, description: str, regenerate: bool) -> Dict[str, Any]:
    try:
        return generate(key, name, description, regenerate=regenerate)
    finally:
        ai_job.release(_inflight, _lock, key)


def schedule(key: str, name: str, description: str, *, regenerate: bool = False) -> bool:
    return ai_job.submit_once(_pool, _inflight, _lock, key, _job, key, name, description, regenerate)


def _due(key: str) -> bool:
    note = _read_fail(key)
    if not note:
        return True
    if int(note.get("attempts", 0)) >= MAX_JOBS:
        return False
    at = float(note.get("at", 0))
    if note.get("reason") == ATTEMPT_STARTED and at < PROCESS_STARTED_AT:
        logger.info("skill_card_art_interrupted", art_id=key)
        return True
    return time.time() - at > RETRY_AFTER_SECONDS


def annotate(locations: Iterable[Dict[str, Any]]) -> int:
    on = AUTO_GENERATE and enabled()
    queued = restyled = 0
    for loc in locations:
        key = art_id(loc["harness"], loc["name"], loc["location_id"])
        path = find(key)
        loc["card_art"] = {"id": key, "rev": hero_images.rev_of(path)} if path else None
        if not on or loc.get("shadowed_by") or not _due(key):
            continue
        if path is None:
            queued += schedule(key, loc["name"], loc.get("description") or "")
        elif restyled < MAX_LOCATIONS and is_stale(key) and schedule(key, loc["name"], loc.get("description") or "", regenerate=True):
            queued += 1
            restyled += 1
    return queued
