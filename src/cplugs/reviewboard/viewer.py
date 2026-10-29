"""The revision viewer: one immutable page, read from the board folder and served to the sandboxed frame (``docs/reviewboard.md``, slice 4).

THE SECURITY MODEL (read before changing anything). A revision page is untrusted code written by an agent. It is served ONLY by the viewer
route, under the sdk's one sandbox policy (``sdk/sandboxed_html.py``: ``sandbox allow-scripts``, ``default-src 'none'``, no network) and
framed by the board page with ``<iframe sandbox="allow-scripts">``, never ``allow-same-origin``, so it runs in an opaque origin with no
cookie, storage or token. The route has no bearer (an iframe cannot send one): the signed ticket (``ticket.py``) is the credential, and it
names a slug, a revision and a view, so a ticket opens exactly one page. This module only READS: it follows no symlink, reads a regular file
inside the board folder, and refuses a file whose sha256 is not the one the sidecar recorded (revision files are immutable).

:func:`page` injects the bridge (``bridge.js``) first in ``<head>`` so the board can point and highlight, and on a scratch board
inlines the post's files as ``data:`` URIs (``scratch_files.resolve``: the frame can fetch nothing, so the page carries them); :func:`load_sidecar` is the cheap
read (one file, no hashing of the other pages) the ticket and open routes use to check a board, revision and view exist.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Tuple, Union

from src.cplugs.reviewboard import document, layout, scratch_files
from src.cplugs.reviewboard.errors import BoardError, BoardNotFound
from src.cplugs.reviewboard.layers import inject as layer_inject
from src.cplugs.reviewboard.schema import MAX_VIEW_BYTES, DraftView, Sidecar, View

BRIDGE_PATH = Path(__file__).with_name("bridge.js")
DRAFT_ID = "draft"
_REVISION = re.compile(r"r[1-9][0-9]*|draft")
_HEAD_OPEN = re.compile(rb"<head(?:\s[^>]*)?>", re.IGNORECASE)
_HTML_OPEN = re.compile(rb"<html(?:\s[^>]*)?>", re.IGNORECASE)
_DOCTYPE = re.compile(rb"^\s*<!doctype[^>]*>", re.IGNORECASE)
MAX_SIDECAR_BYTES = 16 * 1024 * 1024


class PageChanged(BoardError):

    status = 409
    code = "reviewboard_page_changed"


def read_regular(path: Path, limit: int) -> bytes:
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise BoardNotFound("no such page")
        return path.read_bytes()
    except OSError as exc:
        raise BoardNotFound("no such page") from exc


def load_sidecar(root: Path, slug: str) -> Sidecar:
    folder = layout.board_dir(root, slug)
    if folder is None:
        raise BoardNotFound(f"no board {slug} under the boards folder")
    data = read_regular(folder / document.SIDECAR_FILE, MAX_SIDECAR_BYTES)
    try:
        raw = json.loads(data.decode("utf-8"))
        if document.is_newer(raw):
            raise BoardNotFound(f"board {slug} was made by a newer Carnivore and is read only")
        return document.parse_sidecar(raw)
    except ValueError as exc:
        raise BoardNotFound(f"board {slug} cannot be shown") from exc


def find_view(sidecar: Sidecar, revision: str, view: str) -> Union[View, DraftView]:
    if not _REVISION.fullmatch(revision):
        raise BoardNotFound(f"no revision {revision}")
    if revision == DRAFT_ID:
        if sidecar.live is None:
            raise BoardNotFound("this board is not running live")
        draft_row = next((v for v in sidecar.live.draft.views if v.id == view), None)
        if draft_row is None:
            raise BoardNotFound(f"the live draft has no view {view}")
        return draft_row
    rev = next((r for r in sidecar.revisions if r.id == revision), None)
    if rev is None:
        raise BoardNotFound(f"no revision {revision} on this board")
    row = next((v for v in rev.views if v.id == view), None)
    if row is None:
        raise BoardNotFound(f"revision {revision} has no view {view}")
    return row


def bridge_script() -> bytes:
    return b"<script>" + BRIDGE_PATH.read_bytes() + b"</script>"


def inject(page: bytes, script: bytes) -> bytes:
    head = _HEAD_OPEN.search(page)
    if head:
        return page[: head.end()] + script + page[head.end():]
    html = _HTML_OPEN.search(page)
    if html:
        return page[: html.end()] + b"<head>" + script + b"</head>" + page[html.end():]
    doctype = _DOCTYPE.match(page)
    cut = doctype.end() if doctype else 0
    return page[:cut] + script + page[cut:]


def _recorded_page(root: Path, slug: str, revision: str, view: str) -> Tuple[Sidecar, Union[View, DraftView], Path, bytes]:
    sidecar = load_sidecar(root, slug)
    row = find_view(sidecar, revision, view)
    folder = layout.board_dir(root, slug)
    if folder is None:
        raise BoardNotFound(f"no board {slug} under the boards folder")
    data = read_regular(folder / row.file, MAX_VIEW_BYTES)
    if hashlib.sha256(data).hexdigest() != row.sha256:
        raise PageChanged(f"{row.file} is not the page the sidecar recorded")
    return sidecar, row, folder, data


def page(root: Path, slug: str, revision: str, view: str) -> Tuple[bytes, str]:
    try:
        sidecar, row, folder, data = _recorded_page(root, slug, revision, view)
    except PageChanged:
        if revision != DRAFT_ID:
            raise
        sidecar, row, folder, data = _recorded_page(root, slug, revision, view)
    if revision == DRAFT_ID:
        return inject(data, bridge_script()), row.file
    if scratch_files.is_scratch(sidecar):
        data = scratch_files.resolve(data, folder, next(r for r in sidecar.revisions if r.id == revision))
    script = bridge_script()
    layer = next(r for r in sidecar.revisions if r.id == revision).layer
    if layer is not None and view == "main":
        script += layer_inject.layer_bytes(layer.model_dump(mode="json"))
    return inject(data, script), row.file
