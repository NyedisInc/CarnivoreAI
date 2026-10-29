
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

import structlog

from src.config import settings
from src.core import resource_push
from src.core.byoai import gateway as gateway_module, registry
from src.core.byoai.contracts import CAP_CHAT, ByoaiError, InvalidKey, LoginExpired, MissingKey, NotConfigured
from src.core.companies import hero_art_prompt, hero_images
from src.core.resource_push import topics as resource_topics
from src.core.skill_manager import ai_job, scan

logger = structlog.get_logger()

FEATURE_ID = "skills.card_summary"
LABEL_KEY = "ai.feature.skills_card_summary"
DESCRIPTION_KEY = "ai.feature.skills_card_summary.description"
FEATURE_GROUP = "skills"
DIR_NAME = "skill_card_summary"
CHAR_BUDGET = 96
PROMPT_VERSION = "4"
TARGET_CHARS = 80
FIRM_CHARS = 60
MAX_TOKENS = 4000
_DANGLING = frozenset("and or but via using with to for of the a an from by on in into that which as at than so if when while per".split())
BODY_BYTES = 4096
READ_BYTES = 32768
DESCRIPTION_MAX = 600
MAX_JOBS = 3
RETRY_AFTER_SECONDS = 3600
WORKERS = 2
AUTO_GENERATE = True

_SYSTEM = (f"You write the one line brief on a skill card. Reply with one complete plain sentence of at most {TARGET_CHARS} characters that "
           "says what the skill does, starting with a verb. No 'use when', no trigger phrases, no quotes, no markdown, no preamble, "
           "no line breaks, no period at the end.")

_pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="skill-summary")
_inflight: Set[str] = set()
_lock = threading.Lock()


def register_feature() -> None:
    if registry.get_feature(FEATURE_ID) is None:
        registry.register_feature(FEATURE_ID, CAP_CHAT, LABEL_KEY, DESCRIPTION_KEY, group=FEATURE_GROUP)


def summary_key(name: str, description: str, body: str = "") -> str:
    flat = " ".join(description.split())
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    return hashlib.sha256(f"{PROMPT_VERSION}\0{name}\0{flat}\0{body_hash}".encode()).hexdigest()[:32]


def store_dir() -> Path:
    return settings.get_state_dir() / DIR_NAME


def _path(key: str) -> Path:
    return store_dir() / f"{key}.json"


def _fail_path(key: str) -> Path:
    return store_dir() / f"{key}.fail.json"


def find(key: str) -> Optional[str]:
    if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
        return None
    try:
        text = json.loads(_path(key).read_text(encoding="utf-8")).get("text")
    except (OSError, ValueError, AttributeError):
        return None
    return text if isinstance(text, str) and text else None


def _read_fail(key: str) -> Dict[str, Any]:
    return ai_job.read_fail(_fail_path(key))


def _note(key: str, reason: str, *, final: bool = False) -> None:
    attempts = MAX_JOBS if final else int(_read_fail(key).get("attempts", 0)) + 1
    ai_job.write_fail(_fail_path(key), attempts, reason, log_event="skill_card_summary_note_failed")
    logger.warning("skill_card_summary_failed", key=key, reason=reason)


def enabled() -> bool:
    try:
        return gateway_module.get_gateway().store.read().features.get(FEATURE_ID) is not None
    except (ByoaiError, OSError, ValueError) as exc:
        logger.info("skill_card_summary_off", reason=type(exc).__name__)
        return False


def _drop_secret_lines(text: str) -> str:
    kept = "\n".join(line for line in text.splitlines() if not hero_art_prompt.has_secret(line))
    if hero_art_prompt.has_secret(kept):
        kept = "\n".join(part for i, part in enumerate(re.split(r"^```.*$", kept, flags=re.M)) if i % 2 == 0)
    return "" if hero_art_prompt.has_secret(kept) else kept


_BODY_MEMO: Dict[Any, str] = {}


def body_excerpt(folder: Optional[str]) -> str:
    md = scan._skill_md_path(folder) if folder else None
    if md is None:
        return ""
    try:
        info = os.stat(md)
        memo_key = (md, info.st_mtime_ns, info.st_size)
        if memo_key in _BODY_MEMO:
            return _BODY_MEMO[memo_key]
        with open(md, "rb") as handle:
            text = handle.read(READ_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""
    if text.startswith("---"):
        end = re.search(r"^---\s*$", text[3:], flags=re.M)
        text = text[3 + end.end():] if end else ""
    excerpt = _drop_secret_lines(text.strip()[:BODY_BYTES]).strip()
    if len(_BODY_MEMO) > 4096:
        _BODY_MEMO.clear()
    _BODY_MEMO[memo_key] = excerpt
    return excerpt


def _tidy(text: str) -> str:
    flat = re.sub(r"[\s\"`*#]+", " ", text).strip()
    return flat.rstrip(" .,;:!-")


def _first_line(text: str) -> str:
    return next((_tidy(line) for line in text.splitlines() if _tidy(line)), "")


def cut(text: str, budget: int = CHAR_BUDGET) -> str:
    flat = _tidy(text)
    if len(flat) > budget:
        head = flat[:budget]
        if flat[budget] != " ":
            head = head.rsplit(" ", 1)[0] if " " in head else head
        clause = max(head.rfind(", "), head.rfind("; "), head.rfind(": "))
        flat = head[:clause] if clause >= budget // 2 else head
    words = flat.rstrip(" ,;:-").split(" ")
    while len(words) > 1 and words[-1].lower().rstrip(",;:") in _DANGLING:
        words.pop()
    return " ".join(words).rstrip(" ,;:-")


def _first_sentence(text: str) -> str:
    flat = " ".join(text.split())
    hit = re.search(r"[.!?](\s|$)", flat)
    return flat[: hit.start()] if hit else flat


def _body_sentence(body: str) -> str:
    in_fence = False
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line[0] in "#|<>-=!" or line.startswith(("---", "* *")):
            continue
        plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        plain = re.sub(r"[*_`]+", "", plain)
        sentence = _first_sentence(plain)
        if len(sentence.split()) >= 3:
            return sentence
    return ""


def _is_name(name: str, text: str) -> bool:
    squash = lambda value: re.sub(r"[^a-z0-9]", "", value.lower())  # noqa: E731
    return squash(name) == squash(text)


def lead(name: str, description: str, body: str) -> Optional[str]:
    first = _first_sentence(description)
    if first and not _is_name(name, first):
        return cut(first) or None
    sentence = _body_sentence(body)
    return (cut(sentence) or None) if sentence and not _is_name(name, sentence) else None


def build_prompt(name: str, description: str, body: str = "") -> str:
    about = " ".join(description.split())[:DESCRIPTION_MAX]
    if not name.strip() or hero_art_prompt.has_secret(name):
        raise ValueError("name is empty or looks like a secret")
    if hero_art_prompt.has_secret(about) or _is_name(name, about):
        about = ""
    if not about and not body.strip():
        raise ValueError("nothing to summarize")
    prompt = f"skill name: {name.strip()}\nskill description: {about}"
    return f"{prompt}\nskill file excerpt:\n{body.strip()}" if body.strip() else prompt


async def _make(prompt: str) -> str:
    options = dict(system=_SYSTEM, max_tokens=MAX_TOKENS, temperature=0.2, timeout_s=60)
    reply = _first_line((await gateway_module.chat(FEATURE_ID, prompt, **options)).text)
    for limit in (TARGET_CHARS, FIRM_CHARS):
        if len(reply) <= CHAR_BUDGET:
            return reply
        again = f"{prompt}\n\nyour last reply was {len(reply)} characters: {reply}\nshorten that exact sentence to at most {limit} characters, one complete sentence"
        reply = _first_line((await gateway_module.chat(FEATURE_ID, again, **options)).text) or reply
    if len(reply) > CHAR_BUDGET:
        raise ValueError(f"the reply is still over {CHAR_BUDGET} characters after two shortens")
    return reply


def generate(key: str, name: str, description: str, body: str = "", *, regenerate: bool = False) -> Dict[str, Any]:
    if not enabled():
        return {"status": "off"}
    if not regenerate and find(key) is not None:
        return {"status": "exists"}
    try:
        prompt = build_prompt(name, description, body)
    except ValueError as exc:
        _note(key, str(exc), final=True)
        return {"status": "refused", "reason": str(exc)}
    try:
        text = asyncio.run(_make(prompt))
        if not text:
            raise ValueError("the model returned no text")
        hero_images.atomic_write(_path(key), json.dumps({"text": text, "at": time.time()}).encode())
    except (NotConfigured, MissingKey, InvalidKey, LoginExpired) as exc:
        _fail_path(key).unlink(missing_ok=True)
        return {"status": "off", "reason": str(exc)}
    except Exception as exc:
        _note(key, f"{type(exc).__name__}: {str(exc)[:120]}")
        return {"status": "failed", "reason": type(exc).__name__}
    _fail_path(key).unlink(missing_ok=True)
    resource_push.notify(resource_topics.LOCAL_SKILLS)
    logger.info("skill_card_summary_generated", key=key)
    return {"status": "generated"}


def _job(key: str, name: str, description: str, body: str) -> Dict[str, Any]:
    try:
        return generate(key, name, description, body)
    finally:
        ai_job.release(_inflight, _lock, key)


def schedule(key: str, name: str, description: str, body: str = "") -> bool:
    return ai_job.submit_once(_pool, _inflight, _lock, key, _job, key, name, description, body)


def _due(key: str) -> bool:
    return ai_job.retry_due(_read_fail(key), max_jobs=MAX_JOBS, retry_after=RETRY_AFTER_SECONDS)


def prune(current: Set[str]) -> int:
    removed = 0
    try:
        for entry in store_dir().glob("*.json"):
            if entry.name.split(".")[0] not in current:
                entry.unlink(missing_ok=True)
                removed += 1
    except OSError as exc:
        logger.warning("skill_card_summary_prune_failed", error=type(exc).__name__)
    return removed


def current_keys(locations: Iterable[Dict[str, Any]]) -> Set[str]:
    return {summary_key(loc["name"], loc.get("description") or "", body_excerpt(loc.get("path"))) for loc in locations}


def annotate(locations: Iterable[Dict[str, Any]]) -> int:
    shown = enabled()
    on = AUTO_GENERATE and shown
    queued = 0
    for loc in locations:
        description = loc.get("description") or ""
        body = body_excerpt(loc.get("path"))
        key = summary_key(loc["name"], description, body)
        text = find(key) if shown else None
        loc["card_summary"] = text
        loc["card_lead"] = lead(loc["name"], description, body)
        if on and text is None and not loc.get("shadowed_by") and (description.strip() or body) and _due(key):
            queued += schedule(key, loc["name"], description, body)
    return queued
