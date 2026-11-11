
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections import deque
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Tuple

import structlog

from src.core import resource_push
from src.core.argent import classifier_prompt, declare, notices, session_ref, timeline, work_items
from src.core.argent.client import ArgentError, NotFound, Unauthorized
from src.core.argent.store import open_db
from src.core.byoai import registry
from src.core.byoai.contracts import CAP_CHAT, ByoaiError, NotConfigured
from src.core.message_model_secrets import scan_text
from src.core.resource_push import topics

logger = structlog.get_logger()

FEATURE_ID = "argent.classifier"
LABEL_KEY = "ai.feature.argent_classifier"
DESCRIPTION_KEY = "ai.feature.argent_classifier.description"
FEATURE_GROUP = "argent"
MAX_CALLS, WINDOW_SECONDS = 6, 3600.0
SWITCH_AT, MINT_BELOW = 0.8, 0.5
TIMEOUT_SECONDS, MAX_TOKENS = 20.0, 1500
MAX_FILES, MAX_PROMPT_CHARS, MAX_CANDIDATES, MAX_TITLE = 30, 1500, 50, 120
FINISHED = ("closed", "done", "merged", "archived")
TAG = "carnivore-internal"
ASK_KEY = "classifier_ask_every_time"

ChatFn = Callable[..., Awaitable[Any]]

_calls: Dict[str, Deque[float]] = {}


@dataclass(frozen=True)
class Signals:

    branch: str = ""
    files: Tuple[str, ...] = ()
    last_prompt: str = ""


@dataclass
class Outcome:

    action: str = "none"
    reason: str = ""
    work_item_id: str = ""
    confidence: float = 0.0
    detail: Dict[str, Any] = field(default_factory=dict)


def register_feature() -> None:
    if registry.get_feature(FEATURE_ID) is None:
        registry.register_feature(FEATURE_ID, CAP_CHAT, LABEL_KEY, DESCRIPTION_KEY, group=FEATURE_GROUP)


def normalize(title: str) -> str:
    return re.sub(r"[\s\-.]+", "", title or "").lower()


def ask_every_time() -> bool:
    with closing(open_db()) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (ASK_KEY,)).fetchone()
    return bool(row) and row[0] == "1"


def has_connection() -> bool:
    from src.core.byoai import gateway  # noqa: PLC0415

    try:
        gateway.get_gateway().resolve(FEATURE_ID, CAP_CHAT)
    except NotConfigured:
        return False
    return True


def set_ask_every_time(value: bool) -> None:
    with closing(open_db()) as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (ASK_KEY, "1" if value else "0"))


def take_slot(session_key: str, now: float) -> bool:
    window = _calls.setdefault(session_key, deque())
    while window and now - window[0] >= WINDOW_SECONDS:
        window.popleft()
    if len(window) >= MAX_CALLS:
        return False
    window.append(now)
    return True


def clean_signals(signals: Signals) -> Dict[str, Any]:
    files = [f for f in signals.files if isinstance(f, str) and f and not f.startswith(("/", "~")) and ".." not in f.split("/")]
    return {"branch": signals.branch[:200], "files": files[:MAX_FILES], "last_prompt": signals.last_prompt[:MAX_PROMPT_CHARS]}


def has_secret(*texts: str) -> int:
    return sum(len(scan_text(t)) for t in texts if t)


def _candidates(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    by_id = {r["id"]: r for r in rows}
    out = []
    for r in rows:
        if r.get("kind") in ("feature", "story") and str(r.get("status", "")).lower() not in FINISHED:
            parent = by_id.get(r.get("parent_id") or "", {})
            out.append({"id": r["id"], "kind": r["kind"], "title": str(r.get("title", ""))[:MAX_TITLE], "parent": str(parent.get("title", ""))[:MAX_TITLE]})
    return out[:MAX_CANDIDATES]


def project_of(rows: List[Dict[str, Any]], item_id: str) -> str:
    by_id = {r["id"]: r for r in rows}
    current = by_id.get(item_id)
    for _ in range(10):
        if current is None:
            return ""
        if current.get("kind") == "project":
            return str(current["id"])
        current = by_id.get(current.get("parent_id") or "")
    return ""


def parse_answer(text: str, allowed: set) -> Tuple[Dict[str, float], Optional[Tuple[str, float]]]:
    start, end = text.find("{"), text.rfind("}")
    try:
        answer = json.loads(text[start:end + 1]) if 0 <= start < end else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        return {}, None
    raw = answer.get("scores") if isinstance(answer.get("scores"), dict) else {}
    scores = {k: min(1.0, max(0.0, float(v))) for k, v in raw.items() if k in allowed and isinstance(v, (int, float)) and not isinstance(v, bool)}
    new = answer.get("new_feature")
    proposed: Optional[Tuple[str, float]] = None
    if isinstance(new, dict) and isinstance(new.get("title"), str) and isinstance(new.get("confidence"), (int, float)) and not isinstance(new["confidence"], bool):
        title = " ".join(re.sub(r"[\x00-\x1f]", " ", new["title"]).split())[:MAX_TITLE]
        if title:
            proposed = (title, min(1.0, max(0.0, float(new["confidence"]))))
    return scores, proposed


async def _mint(client: Any, tenant: str, rows: List[Dict[str, Any]], parent_id: str, title: str) -> Optional[str]:
    same = next((r for r in rows if r.get("kind") == "feature" and r.get("parent_id") == parent_id and normalize(str(r.get("title"))) == normalize(title)), None)
    if same is not None:
        return str(same["id"])
    try:
        reply = await client.post("/v1/my/work-items", json={"kind": "feature", "parent_id": parent_id, "title": title})
    except (NotFound, ArgentError) as exc:
        logger.info("argent_classifier_mint_refused", status=exc.status)
        return None
    row = reply.body.get("item") if isinstance(reply.body.get("item"), dict) else reply.body
    if not await asyncio.to_thread(work_items.upsert, tenant, row):
        return None
    resource_push.notify(topics.ARGENT_WORK_ITEMS)
    return str(row["id"])


async def report_spend(client: Any, ref: str, project_id: str, result: Any) -> None:
    usage = getattr(result, "usage", None)
    raw = getattr(result, "raw", None)
    turn: Dict[str, Any] = {"request_id": f"carnivore-classifier-{uuid.uuid4().hex}", "sub_agent_id": "", "tag": TAG,
                            "model": str(raw.get("model", "")) if isinstance(raw, dict) else "",
                            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "input_tokens": getattr(usage, "input_tokens", None) or 0, "output_tokens": getattr(usage, "output_tokens", None) or 0}
    if project_id:
        turn["work_item_id"] = project_id
    try:
        await client.post(f"/v1/my/agent-sessions/{ref}/usage", json={"turns": [turn]})
    except (NotFound, ArgentError) as exc:
        logger.info("argent_classifier_spend_not_reported", status=exc.status)


async def classify(tmux_name: str, signals: Signals, *, chat: Optional[ChatFn] = None, now: Optional[float] = None, display_name: str = "", auto: bool = False) -> Outcome:
    if not timeline.is_running():
        return Outcome(reason="feature_off")
    try:
        client, tenant = await work_items.client_for_call()
    except Unauthorized:
        return Outcome(reason="login_required")
    rows = (await asyncio.to_thread(work_items.list_rows, tenant))["items"]
    candidates = _candidates(rows)
    if not candidates:
        return Outcome(reason="no_candidates")
    sent = clean_signals(signals)
    found = has_secret(sent["branch"], sent["last_prompt"], *sent["files"])
    if found:
        logger.info("argent_classifier_blocked_secret", findings=found)
        return Outcome(reason="blocked_secret")
    ref = await asyncio.to_thread(session_ref.ref_for_name, tenant, tmux_name)
    declared = await asyncio.to_thread(timeline.current, tenant, ref)
    if auto and any(d["sub_agent_id"] == "" and d["reason"] != "classifier" for d in declared):
        return Outcome(reason="picked")
    moment = time.time() if now is None else now
    if not take_slot(ref, moment):
        return Outcome(reason="rate_limited")
    current_id = timeline.effective(declared, "")
    if chat is None:
        from src.core.byoai import gateway
        chat = gateway.chat
    try:
        result = await asyncio.wait_for(chat(FEATURE_ID, classifier_prompt.build(sent, candidates, current_id), system=classifier_prompt.SYSTEM,
                                             max_tokens=MAX_TOKENS, temperature=0, timeout_s=TIMEOUT_SECONDS), TIMEOUT_SECONDS)
    except NotConfigured:
        _calls[ref].pop()
        return Outcome(reason="no_ai_connection")
    except asyncio.TimeoutError:
        return Outcome(reason="ai_timeout")
    except ByoaiError as exc:
        logger.info("argent_classifier_ai_failed", error_type=type(exc).__name__)
        return Outcome(reason="ai_error")
    project_id = project_of(rows, current_id) or project_of(rows, candidates[0]["id"])
    await report_spend(client, ref, project_id, result)
    scores, proposed = parse_answer(getattr(result, "text", "") or "", {c["id"] for c in candidates})
    if not scores and proposed is None:
        return Outcome(reason="ai_output_invalid")
    best_id, best = max(scores.items(), key=lambda kv: kv[1], default=("", 0.0))
    minted = False
    target, confidence = best_id, best
    if best < MINT_BELOW and proposed is not None and proposed[1] >= SWITCH_AT and not has_secret(proposed[0]):
        parent = project_of(rows, current_id) or project_of(rows, best_id) or project_id
        new_id = await _mint(client, tenant, rows, parent, proposed[0]) if parent else None
        if new_id is None:
            return Outcome(reason="mint_refused")
        target, confidence, minted = new_id, proposed[1], True
    if not target or confidence < SWITCH_AT:
        return Outcome(reason="sticky", work_item_id=current_id, confidence=confidence)
    if target == current_id:
        return Outcome(reason="already_there", work_item_id=current_id, confidence=confidence)
    ask = await asyncio.to_thread(ask_every_time)
    title = next((str(r["title"]) for r in rows if r["id"] == target), proposed[0] if minted and proposed else "")
    previous = next((str(r["title"]) for r in rows if r["id"] == current_id), "")
    if not ask:
        try:
            await declare.declare(tmux_name, target, "classifier")
        except declare.DeclareError as exc:
            return Outcome(reason=exc.code, work_item_id=target, confidence=confidence)
    notices.classifier_fix(tmux_name, display_name, title, previous, ask)
    action = ("minted_and_" if minted else "") + ("asked" if ask else "switched")
    return Outcome(action=action, work_item_id=target, confidence=confidence, detail={"previous": current_id})
