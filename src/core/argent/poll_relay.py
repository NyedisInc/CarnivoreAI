
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core import resource_push
from src.core.argent import cost_poller, health
from src.core.argent import settings as settings_module
from src.core.argent.pair_credential import PairRefused, PostFn
from src.core.resource_push import topics

logger = structlog.get_logger()

CAP_POLL = "argent.pair.poll"
POLL_PATH = "/federation/argent/poll"
MAX_BYTES = 256 * 1024
STALE_SECONDS = 120.0
BACKOFF_SECONDS = 300.0


class PollBody(BaseModel):
    """One relayed poll result. No token, no key, no address: ``health`` is the public report, ``cost`` the cost snapshot. The sender is the authenticated peer."""

    model_config = ConfigDict(extra="forbid")

    as_of: float = Field(ge=0)
    health: Dict[str, Any]
    cost: Dict[str, Any]

    @field_validator("cost", "health")
    @classmethod
    def _small(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if len(json.dumps(value, default=str)) > MAX_BYTES:
            raise ValueError("too large")
        return value


def build_body(now: float) -> Optional[PollBody]:
    report, snap = health.latest(), cost_poller.snapshot()
    if report.state != health.UP or snap.get("state") in (None, "pending"):
        return None
    return PollBody(as_of=now, health=report.as_public(), cost=snap)


class PollSender:

    def __init__(self, links: Callable[[], List[Tuple[str, PostFn, List[str]]]], clock: Callable[[], float] = time.time) -> None:
        self._links, self._clock = links, clock
        self._last: Dict[str, str] = {}
        self._backoff: Dict[str, float] = {}
        self.sent: Dict[str, str] = {}

    async def after_poll(self) -> List[str]:
        now = self._clock()
        if not settings_module.read().enabled:
            return []
        body = build_body(now)
        if body is None:
            return []
        data = body.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps({k: v for k, v in data.items() if k != "as_of"}, sort_keys=True, default=str).encode()).hexdigest()
        took: List[str] = []
        for iid, post, caps in self._links():
            if CAP_POLL not in caps or self._last.get(iid) == digest or self._backoff.get(iid, 0.0) > now:
                continue
            try:
                status, _ = await post("POST", POLL_PATH, data)
            except Exception as exc:  # noqa: BLE001
                logger.info("argent_poll_relay_failed", target=iid, error=type(exc).__name__)
                self.sent[iid] = "failed"
                continue
            if status == 200:
                self._last[iid], self.sent[iid] = digest, "applied"
                took.append(iid)
            elif status == 409:
                self._backoff[iid], self.sent[iid] = now + BACKOFF_SECONDS, "polls_itself"
            else:
                self.sent[iid] = "refused" if status in (401, 403, 422) else "failed"
        return took


class _Relayed:

    sender = ""
    received_at = 0.0
    body: Optional[PollBody] = None


def receive(sender: str, body: PollBody, *, listed: Callable[[str], bool], clock: Callable[[], float] = time.time) -> None:
    if not settings_module.read().enabled:
        raise PairRefused("feature_off", 409)
    if not listed(sender):
        raise PairRefused("not_listed", 403)
    if health.latest().state == health.UP:
        raise PairRefused("polls_itself", 409)
    _Relayed.sender, _Relayed.received_at, _Relayed.body = sender, clock(), body
    resource_push.notify(topics.ARGENT_PAIR)


def relayed(clock: Callable[[], float] = time.time) -> Optional[Dict[str, Any]]:
    body = _Relayed.body
    if body is None:
        return None
    return {"from": _Relayed.sender, "received_at": _Relayed.received_at, "stale": clock() - _Relayed.received_at > STALE_SECONDS,
            "health": body.health, "cost": body.cost}


def forget() -> None:
    _Relayed.sender, _Relayed.received_at, _Relayed.body = "", 0.0, None
