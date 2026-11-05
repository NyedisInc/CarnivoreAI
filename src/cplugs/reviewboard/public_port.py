
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from src.cplugs.reviewboard import layout, viewer, wire
from src.cplugs.reviewboard.errors import BoardError
from src.cplugs.reviewboard.layers import inject as layer_inject
from src.cplugs.reviewboard.schema import MAX_VIEW_BYTES, Revision
from src.cplugs.sdk import CplugContext, ports
from src.cplugs.sdk.board_public import PORT, PublicBoardMissing, PublicBoardUnavailable, PublicRevision, RevisionTexts

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


def register(ctx: CplugContext) -> None:
    ports.register(NAME, PublicPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)
