
from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Any, Dict

import structlog

from src.cplugs.devwidgetlab.drafts import checkout, create, files, preview, session, ship, store
from src.cplugs.devwidgetlab.errors import BuildBusy, DraftNotFound

logger = structlog.get_logger()


def list_drafts(storage: Path) -> Dict[str, Any]:
    source = checkout.status(storage)
    if not store.checkout_available(storage):
        return {"available": False, "reason": "no_checkout", "building": None, "drafts": [], "source": source}
    return {"available": True, "reason": "", "building": preview.building_slug(), "drafts": store.list_drafts(storage), "source": source}


def create_draft(storage: Path, body: Dict[str, Any]) -> Dict[str, Any]:
    if body["kind"] == "new":
        return create.create_new(storage, body["name"], body["what"], list(body["hosts"]), list(body["sizes"]), body["category"])
    return create.create_revision(storage, body["widget"], body["name"], body["what"], dict(body["context"]))


def get_draft(storage: Path, slug: str) -> Dict[str, Any]:
    store.require_checkout(storage)
    return store.summary(store.existing_dir(storage, slug))


async def build_draft(storage: Path, slug: str) -> Dict[str, Any]:
    return await preview.start_build_off_loop(storage, slug)


def ticket(storage: Path, slug: str) -> Dict[str, Any]:
    root = store.require_checkout(storage)
    build = store.read_build(store.existing_dir(storage, slug))
    if build.get("state") != "built":
        raise DraftNotFound("this draft has no finished build; build it first")
    return {**preview.mint_ticket(slug), "rebuild": store.build_stale(build, root, store.head_sha(root))}


async def open_page(storage: Path, slug: str) -> Dict[str, Any]:
    answer = await asyncio.to_thread(ticket, storage, slug)
    if not answer["rebuild"]:
        return answer
    try:
        await preview.start_build_off_loop(storage, slug)
    except BuildBusy:
        logger.info("widget_lab_stale_rebuild_deferred", slug=slug, building=preview.building_slug())
        return {**answer, "rebuild": False}
    logger.info("widget_lab_stale_rebuild_started", slug=slug)
    return answer


def ship_plan(storage: Path, slug: str) -> Dict[str, Any]:
    repo = store.require_checkout(storage)
    folder = store.existing_dir(storage, slug)
    apply_command = (f"cd {shlex.quote(str(repo))} && venv/bin/python3 -m src.cplugs.devwidgetlab.drafts.ship_cli "
                     f"--draft {shlex.quote(str(folder))} --repo {shlex.quote(str(repo))} --apply")
    return {**ship.plan(folder, repo), "repo": str(repo), "apply_command": apply_command}


def discard_draft(storage: Path, slug: str) -> Dict[str, Any]:
    store.require_checkout(storage)
    return {"discarded": str(store.discard(storage, slug))}


async def hand_to_claude(ctx: Any, storage: Path, slug: str) -> Dict[str, Any]:
    return await session.hand_to_claude(ctx, storage, slug)


def _folder(storage: Path, slug: str) -> Path:
    store.require_checkout(storage)
    return store.existing_dir(storage, slug)


def files_list(storage: Path, slug: str) -> Dict[str, Any]:
    return {"slug": slug, "files": files.list_files(_folder(storage, slug))}


def file_get(storage: Path, slug: str, path: str) -> Dict[str, Any]:
    return files.read_file(_folder(storage, slug), path)


def file_set(storage: Path, slug: str, path: str, content: str) -> Dict[str, Any]:
    return files.write_file(_folder(storage, slug), path, content)


def file_delete(storage: Path, slug: str, path: str) -> Dict[str, Any]:
    return files.delete_file(_folder(storage, slug), path)
