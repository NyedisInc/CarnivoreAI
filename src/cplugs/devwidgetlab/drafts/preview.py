
from __future__ import annotations

import asyncio
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.cplugs.devwidgetlab.drafts import store
from src.cplugs.devwidgetlab.errors import BuildBusy, DraftInvalid, DraftNotFound, NoCheckout
from src.cplugs.sdk import signed_links

logger = structlog.get_logger()

SITE_FOLDER = "site"
LOG_FILE = "build.log"
BUILD_RECORD = "build.json"
CONFIG_FILE = "vite.widget-draft.config.ts"
TIMEOUT_SECONDS = 600
TICKET_TTL_S = 3600
TICKET_LABEL = "devwidgetlab-draft-harness-v1"
SERVE_PREFIX = "/api/v1/cplugs/devwidgetlab/draft-harness"

_job: Dict[str, Any] = {"task": None, "slug": None}


def vite_bin(repo: Path) -> Path:
    return repo / "web" / "node_modules" / ".bin" / "vite"


def require_buildable(storage_path: Path) -> Path:
    repo = store.require_checkout(storage_path)
    if not vite_bin(repo).is_file() or not (repo / "web" / CONFIG_FILE).is_file():
        raise NoCheckout("no_web_dependencies")
    return repo


def build_argv(repo: Path) -> list[str]:
    return [str(vite_bin(repo)), "build", "--config", CONFIG_FILE, "--configLoader", "runner"]


def build_env(folder: Path) -> Dict[str, str]:
    return {**os.environ, "LAB_DRAFT_DIR": str(folder)}


def is_building() -> bool:
    task = _job["task"]
    return bool(task and not task.done())


def _record(folder: Path, **fields: Any) -> None:
    path = folder / store.BUILD_FOLDER / BUILD_RECORD
    store.write_json(path, {"state": "none", "sha": None, "root": None, "built_at": None, "log": None, "error": "", **fields})
    store.set_fields(folder, state=fields["state"])


async def _run(folder: Path, repo: Path) -> None:
    build = folder / store.BUILD_FOLDER
    log = build / LOG_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    sha = await asyncio.to_thread(store.head_sha, repo)
    where = str(repo)
    try:
        with log.open("wb") as sink:
            proc = await asyncio.create_subprocess_exec(*build_argv(repo), cwd=str(repo / "web"), env=build_env(folder), stdout=sink, stderr=asyncio.subprocess.STDOUT)
            try:
                await asyncio.wait_for(proc.wait(), timeout=TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                _record(folder, state="failed", sha=sha, root=where, log=str(log), error=f"the build took longer than {TIMEOUT_SECONDS} seconds")
                return
        if proc.returncode == 0 and (build / SITE_FOLDER / "index.html").is_file():
            _record(folder, state="built", sha=sha, root=where, built_at=time.strftime("%Y-%m-%dT%H:%M:%S"), log=str(log))
        else:
            _record(folder, state="failed", sha=sha, root=where, log=str(log), error=_first_error(log, proc.returncode))
    except OSError as exc:
        logger.warning("widget_lab_draft_build_failed", slug=folder.name, error_type=type(exc).__name__, error=str(exc))
        _record(folder, state="failed", sha=sha, root=where, log=str(log), error=f"{type(exc).__name__}: {exc}")


def _first_error(log: Path, code: Optional[int]) -> str:
    try:
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if "error" in line.lower():
                return line.strip()[:300]
    except OSError:
        pass
    return f"the build exited {code}"


def start_build(storage_path: Path, slug: str) -> Dict[str, Any]:
    """Start a draft's build in the background. Inputs: storage_path; slug. Output: the draft's summary (state ``building``).

    Raises: NoCheckout, DraftInvalid, DraftNotFound, BuildBusy (a build is already running).
    """
    repo = require_buildable(storage_path)
    folder = store.existing_dir(storage_path, slug)
    if is_building():
        raise BuildBusy(f"a build is already running for {_job['slug']}")
    store.write_overrides_note(folder, store.read_record(folder))
    (folder / store.BUILD_FOLDER).mkdir(exist_ok=True)
    _record(folder, state="building", log=str(folder / store.BUILD_FOLDER / LOG_FILE))
    _job.update(task=asyncio.ensure_future(_run(folder, repo)), slug=slug)
    return store.summary(folder)


def building_slug() -> Optional[str]:
    return _job["slug"] if is_building() else None


def mint_ticket(slug: str) -> Dict[str, Any]:
    store.check_slug(slug)
    return {"path": f"{SERVE_PREFIX}/{signed_links.mint(TICKET_LABEL, [slug], TICKET_TTL_S)}/index.html", "expires_in": TICKET_TTL_S}


def resolve_file(storage_path: Path, ticket: str, rel: str) -> Path:
    store.require_checkout(storage_path)
    fields = signed_links.verify(TICKET_LABEL, ticket, 1)
    if fields is None:
        raise DraftNotFound("no such draft page")
    try:
        site = (store.draft_dir(storage_path, fields[0]) / store.BUILD_FOLDER / SITE_FOLDER).resolve()
    except DraftInvalid as exc:
        raise DraftNotFound("no such draft page") from exc
    target = (site / (rel or "index.html")).resolve()
    if not target.is_relative_to(site) or not target.is_file():
        raise DraftNotFound("no such draft page")
    return target


def media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
