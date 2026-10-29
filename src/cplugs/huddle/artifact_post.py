
from __future__ import annotations

from typing import Any, Dict

from src.cplugs.huddle import artifacts, files, kinds, service, task_files
from src.cplugs.huddle.rules import CLAUDE
from src.cplugs.sdk import CplugContext


def post(ctx: CplugContext, item_id: int, title: Any, description: Any, html: Any, *, author_key: str = "") -> Dict[str, Any]:
    title, description, data = artifacts.clean(title, description, html)
    store = service.store(ctx)
    store.item(item_id)
    folder = task_files.folder_for(ctx, item_id, task_files.ARTIFACTS)
    saved = files.save(ctx.storage, item_id, artifacts.FILE_NAME, data, folder)
    parts = artifacts.parts_of(files.describe(ctx.storage, item_id, saved["id"], [folder] if folder else ()), title, description)
    text = f"{title}: {description}" if description else title
    return store.post(item_id, text, actor=CLAUDE, kind=kinds.INFO, author_key=author_key, parts=parts, notify=True)
