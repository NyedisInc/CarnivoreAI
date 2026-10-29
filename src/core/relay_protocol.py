
from __future__ import annotations

import json
import os
import random
import secrets
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional

from src.core import relay_keychain

PUBLISH_SUBPROTOCOL = "cloude.relay.publish.v1"

TOKEN_ENVS = ("CARNIVORE_RELAY_PUBLISH_TOKEN", "CLOUDE_RELAY_PUBLISH_TOKEN")

BACKOFF_INITIAL_SECONDS = 2.0
BACKOFF_CAP_SECONDS = 60.0


@dataclass(frozen=True)
class LinkDeclaration:

    link_id: str
    token_sha256: str
    session_id: str
    nonce: Optional[str] = None
    expires_at: Optional[int] = None
    content_key: Optional[bytes] = field(default=None, repr=False)


def publish_token(
    environ: Optional[Mapping[str, str]] = None,
    keychain: Optional[Callable[[], Optional[str]]] = None,
) -> Optional[str]:
    env = os.environ if environ is None else environ
    for name in TOKEN_ENVS:
        value = env.get(name, "").strip()
        if value:
            return value
    reader = relay_keychain.read_publish_token if keychain is None else keychain
    return (reader() or "").strip() or None


def new_publisher_id() -> str:
    return secrets.token_hex(16)


def links_frame(declarations: Iterable[LinkDeclaration], publisher_id: str) -> str:
    return json.dumps({
        "type": "links",
        "publisher_id": publisher_id,
        "links": [
            {"link_id": d.link_id, "token_sha256": d.token_sha256,
             "session_id": d.session_id}
            for d in declarations
        ],
    })


def data_frame(link_id: str, payload: str) -> str:
    return json.dumps({"type": "data", "link_id": link_id, "payload": payload})


def size_frame(link_id: str, cols: int, rows: int) -> str:
    return json.dumps({"type": "size", "link_id": link_id, "cols": cols, "rows": rows})


def joined_link_id(text: str) -> Optional[str]:
    try:
        frame = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(frame, dict) or frame.get("type") != "joined":
        return None
    link_id = frame.get("link_id")
    return link_id if isinstance(link_id, str) and link_id else None


def backoff_delay(attempt: int, rng: Callable[[], float] = random.random) -> float:
    step = min(BACKOFF_CAP_SECONDS, BACKOFF_INITIAL_SECONDS * (2 ** max(attempt, 0)))
    return min(BACKOFF_CAP_SECONDS, step + rng() * step / 4)
