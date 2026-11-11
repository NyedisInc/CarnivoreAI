
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

import structlog

from src.cplugs.reviewboard import board_look, layout, ports, viewer, visitor_checks, wire
from src.cplugs.reviewboard.errors import BoardError
from src.cplugs.reviewboard.layers import inject as layer_inject
from src.cplugs.reviewboard.schema import MAX_VIEW_BYTES, Revision
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk import ports as sdk_ports
from src.cplugs.reviewboard.public.port import PORT, PublicBoardMissing, PublicBoardUnavailable, PublicRevision, RevisionTexts
from src.cplugs.sdk.computer import local_computer

logger = structlog.get_logger()
NAME = PORT


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _revision_strings(revision: Revision) -> List[str]:
    out = [revision.summary, *(view.label for view in revision.views)]
    for prompt in revision.prompts:
        out.append(prompt.label)
        out.extend(option.label for option in prompt.options or [])
    out.extend(anchor.label for anchor in revision.anchors)
    if revision.layer is not None:
        out.extend(_strings(revision.layer.model_dump(mode="json")))
    return out


@dataclass(frozen=True)
class _Loaded:

    wanted: str
    latest: str
    title: str
    revision: Revision
    texts: Tuple[str, ...]
    pages: Dict[str, bytes]


def _projection(title: str, rev: Revision) -> Dict[str, Any]:
    return {
        "title": title, "revision": rev.id, "summary": rev.summary, "viewport": rev.viewport, "max_width": rev.max_width,
        "views": [{"id": v.id, "label": v.label} for v in rev.views],
        "prompts": [{"id": p.id, "kind": p.kind, "label": p.label, "anchor": p.anchor,
                     "options": [{"id": o.id, "label": o.label} for o in p.options or []]} for p in rev.prompts],
        "anchors": [{"id": a.id, "label": a.label} for a in rev.anchors],
        "layer": rev.layer.model_dump(mode="json") if rev.layer is not None else None,
    }


def _revision_number(revision: str) -> int:
    return int(revision[1:])


def _public_page(data: bytes, rev: Revision, view_id: str) -> bytes:
    try:
        script = viewer.bridge_script()
        if rev.layer is not None and view_id == "main":
            script += layer_inject.layer_bytes(rev.layer.model_dump(mode="json"))
    except OSError as exc:
        raise PublicBoardUnavailable(f"the page additions cannot be read ({type(exc).__name__})") from exc
    return viewer.inject(data, script)


class PublicPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    def _load(self, slug: str, revision: Optional[str]) -> _Loaded:
        try:
            root = wire.board_root(self._ctx)
            sidecar = viewer.load_sidecar(root, slug)
            latest = sidecar.revisions[-1].id
            wanted = revision or latest
            chosen = next((r for r in sidecar.revisions if r.id == wanted), None)
            folder = layout.board_dir(root, slug)
            if chosen is None or folder is None:
                raise PublicBoardMissing(f"board {slug} has no revision {wanted}")
            texts = [sidecar.board.title, *_revision_strings(chosen)]
            pages: Dict[str, bytes] = {}
            for view in chosen.views:
                data = viewer.read_regular(folder / view.file, MAX_VIEW_BYTES)
                if hashlib.sha256(data).hexdigest() != view.sha256:
                    raise PublicBoardMissing(f"{view.file} is not the page the sidecar recorded")
                pages[view.id] = data
                texts.append(data.decode("utf-8", errors="replace"))
        except BoardError as exc:
            raise PublicBoardMissing(str(exc)) from exc
        return _Loaded(wanted, latest, sidecar.board.title, chosen, tuple(texts), pages)

    def revision_texts(self, slug: str, revision: Optional[str] = None) -> RevisionTexts:
        loaded = self._load(slug, revision)
        return RevisionTexts(slug=slug, revision=loaded.wanted, latest=loaded.latest, title=loaded.title, texts=loaded.texts)

    def public_revision(self, slug: str, revision: str, view: Optional[str] = None) -> PublicRevision:
        loaded = self._load(slug, revision)
        page = None
        if view is not None:
            if view not in loaded.pages:
                raise PublicBoardMissing(f"revision {loaded.wanted} has no view {view}")
            page = _public_page(loaded.pages[view], loaded.revision, view)
        return PublicRevision(slug, loaded.wanted, loaded.latest, loaded.texts, _projection(loaded.title, loaded.revision), page)

    def latest(self, slug: str) -> str:
        try:
            return viewer.load_sidecar(wire.board_root(self._ctx), slug).revisions[-1].id
        except BoardError as exc:
            raise PublicBoardMissing(str(exc)) from exc

    def board_theme(self, slug: str) -> Optional[Dict[str, str]]:
        look = board_look.read(self._ctx.storage.path, slug)
        return dict(look["palette"]) if look else None

    def check_post(self, slug: str, revision: str, kind: str, body: Mapping[str, Any]) -> List[str]:
        return visitor_checks.problems(self._load(slug, revision).revision, kind, body)

    def follow(self, listener: Callable[[], None]) -> Callable[[], None]:
        return self._ctx.follow(TOPIC, lambda topics: listener())

    async def forward(self, slug: str, text: str, revisions: List[str]) -> Dict[str, Any]:
        try:
            sidecar = await asyncio.to_thread(viewer.load_sidecar, wire.board_root(self._ctx), slug)
        except BoardError as exc:
            raise PublicBoardMissing(str(exc)) from exc
        task = sidecar.task
        if task is None:
            return {"posted": False, "reason": "the board has no task"}
        here = local_computer()
        if task.computer and here and task.computer != here:
            return {"posted": False, "reason": f"the task is on {task.computer}"}
        port = ports.find()
        if port is None:
            return {"posted": False, "reason": "the task manager is off"}
        posted = await port.post_visitors(task.item_id, text, {"slug": slug, "revisions": sorted(set(revisions), key=_revision_number)})
        logger.info("reviewboard_visitors_forwarded", slug=slug, item=task.item_id, posted=bool(posted.get("posted")))
        if not posted.get("posted"):
            return {"posted": False, "reason": str(posted.get("reason") or "the task did not take the reply")[:300]}
        return {"posted": True, "message_id": posted["message_id"], "item_id": task.item_id}


def register(ctx: CplugContext) -> None:
    sdk_ports.register(NAME, PublicPort(ctx))


def unregister() -> None:
    sdk_ports.unregister(NAME)
