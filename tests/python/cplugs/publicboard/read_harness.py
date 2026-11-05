
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.cplugs.publicboard.edge import EdgeConfig, PublicEdge
from src.cplugs.reviewboard import document
from tests.python.cplugs.reviewboard.boards import SIDECAR

PEER = "203.0.113.11"
HOST = b"review.example.test"
HEADER = "carnivore-board-link"


@dataclass(frozen=True)
class Answer:

    status: int
    headers: Dict[str, str]
    body: bytes

    def json(self) -> Dict[str, Any]:
        return json.loads(self.body)


def edge() -> PublicEdge:
    return PublicEdge(EdgeConfig.of([PEER], [HOST.decode()]))


async def call(app: PublicEdge, path: str, token: Optional[str] = None, extra: Tuple[Tuple[str, str], ...] = (), method: str = "GET",
               query: bytes = b"", peer: str = PEER, forwarded: Optional[str] = "198.51.100.1") -> Answer:
    if forwarded is not None and not any(k.lower() == "x-forwarded-for" for k, _ in extra):
        extra = (*extra, ("X-Forwarded-For", forwarded))
    headers = [(b"host", HOST)] + [(k.lower().encode(), v.encode()) for k, v in extra]
    if token is not None:
        headers.append((HEADER.encode(), token.encode()))
    scope = {"type": "http", "method": method, "raw_path": path.encode(), "path": path, "query_string": query, "headers": headers, "client": (peer, 40000)}
    sent: List[Dict[str, Any]] = []

    async def receive() -> Dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return Answer(start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, body)


def rewrite(folder: Path, mutate: Any) -> None:
    raw = json.loads((folder / document.SIDECAR_FILE).read_text())
    mutate(raw)
    (folder / document.SIDECAR_FILE).write_text(document.canonical_text(document.parse_sidecar(raw)), encoding="utf-8")


def add_revision(folder: Path, page: bytes, summary: str = "second pass") -> str:
    raw = json.loads((folder / document.SIDECAR_FILE).read_text())
    number = len(raw["revisions"]) + 1
    new = copy.deepcopy(raw["revisions"][-1])
    name = f"r{number:03d}.html"
    (folder / name).write_bytes(page)
    new.update(id=f"r{number}", n=number, summary=summary, answers_round=None)
    new["views"] = [{"id": "main", "label": "bar", "file": name, "sha256": hashlib.sha256(page).hexdigest(), "bytes": len(page)}]
    raw["revisions"].append(new)
    (folder / document.SIDECAR_FILE).write_text(document.canonical_text(document.parse_sidecar(raw)), encoding="utf-8")
    return new["id"]


def leaky_strings() -> List[str]:
    task = SIDECAR["task"]
    first_round = SIDECAR["rounds"][0]
    return [SIDECAR["board"]["created_by"]["session"], SIDECAR["board"]["created_by"]["label"], task["title_at_link"], task["github_issue"],
            task["list"], task["computer"], SIDECAR["revisions"][0]["source_commit"], first_round["note"], first_round["answers"][2]["text"],
            first_round["anchor_notes"][0]["text"], "r001.html", "message_id", "item_id", "attachments"]


def get(app: PublicEdge, path: str, token: Optional[str] = None, **kw: Any) -> Answer:
    import asyncio
    return asyncio.run(call(app, path, token, **kw))


def mint_token(store: Any, board: str = SIDECAR["board"]["slug"], mode: str = "pinned", ttl: str = "1d") -> str:
    import asyncio
    from types import SimpleNamespace

    from src.cplugs.publicboard import minting
    return asyncio.run(minting.mint_link(SimpleNamespace(storage=store), board, ttl, mode))["token"]
