
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Set

import structlog

from src.config.catalog import CATALOG_KEY
from src.core import config_writer
from src.core.catalog import catalog_auth, guest_account, hosted_api

logger = structlog.get_logger(__name__)

_ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_running: Set["asyncio.Task[str]"] = set()

Call = Callable[..., Awaitable[hosted_api.HostedAnswer]]


async def _token(
    state_dir: Path, api_base_url: str, open_db: Callable[[], Any], call: Call, clock: Callable[[], float]
) -> str:
    try:
        return await catalog_auth.bearer(state_dir, api_base_url, clock, allow_guest=True)
    except catalog_auth.SignedOut:
        return await guest_account.ensure_guest_session(
            state_dir=state_dir, api_base_url=api_base_url, call=call, clock=clock,
            install_id=lambda: guest_account.install_id_from(open_db),
        )


async def report_installed(
    *,
    state_dir: Path,
    api_base_url: str,
    open_db: Callable[[], Any],
    item_id: str,
    version: str,
    call: Call = hosted_api.call,
    clock: Callable[[], float] = time.time,
) -> str:
    if not _ITEM_ID.match(item_id):
        logger.warning("catalog_install_report_bad_item", item_id=item_id)
        return "bad_item"
    try:
        token = await _token(state_dir, api_base_url, open_db, call, clock)
    except guest_account.GuestUnavailable as exc:
        return exc.code
    except (catalog_auth.RotationFailed, hosted_api.HostedUnavailable) as exc:
        logger.warning("catalog_install_report_token_unavailable", error=type(exc).__name__)
        return "unreachable"
    try:
        answer = await call(
            api_base_url, "POST", f"/items/{item_id}/installed",
            json_body={"version": version}, bearer=token,
        )
    except hosted_api.HostedUnavailable as exc:
        logger.warning("catalog_install_report_unreachable", item_id=item_id, code=exc.code)
        return "unreachable"
    if answer.status >= 400:
        logger.warning("catalog_install_report_refused", item_id=item_id, status=answer.status)
        return "limited" if answer.status == 429 else "refused"
    return "sent"


_RETRY = frozenset({"unreachable", "keychain_unavailable", "guest_refused", "limited"})

BACKFILL_KEY = "install_backfill_done"


def backfill_done(config_path: Path) -> bool:
    try:
        block = json.loads(Path(config_path).read_text()).get(CATALOG_KEY)
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(block, dict) and block.get(BACKFILL_KEY) is True


def _mark_backfilled(config_path: Path) -> None:
    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        existing = config.get(CATALOG_KEY)
        block = dict(existing) if isinstance(existing, dict) else {}
        if block.get(BACKFILL_KEY) is True:
            return None
        block[BACKFILL_KEY] = True
        return {**config, CATALOG_KEY: block}

    config_writer.commit(Path(config_path).expanduser(), mutate)


async def backfill_installed(
    *,
    config_path: Path,
    state_dir: Path,
    api_base_url: str,
    open_db: Callable[[], Any],
    ledger: Callable[[], Any],
    call: Call = hosted_api.call,
    clock: Callable[[], float] = time.time,
) -> str:
    if await asyncio.to_thread(backfill_done, config_path):
        return "already"

    def pairs() -> Set[Any]:
        with ledger() as led:
            return {(row.item_id, row.version) for row in led.list()}

    for item_id, version in sorted(await asyncio.to_thread(pairs)):
        result = await report_installed(
            state_dir=state_dir, api_base_url=api_base_url, open_db=open_db,
            item_id=item_id, version=version, call=call, clock=clock,
        )
        if result in _RETRY:
            logger.info("catalog_install_backfill_paused", result=result)
            return "retry"
    await asyncio.to_thread(_mark_backfilled, config_path)
    logger.info("catalog_install_backfill_done")
    return "done"


def _spawn(coro: Awaitable[str]) -> None:
    task = asyncio.get_running_loop().create_task(coro)  # type: ignore[arg-type]
    _running.add(task)

    def _done(finished: "asyncio.Task[str]") -> None:
        _running.discard(finished)
        if not finished.cancelled() and finished.exception() is not None:
            logger.warning("catalog_install_report_failed", error=repr(finished.exception()))

    task.add_done_callback(_done)


def schedule(**kwargs: Any) -> None:
    _spawn(report_installed(**kwargs))


def schedule_for(services: Any, item_id: str, version: str) -> None:
    schedule(
        state_dir=services.settings_reader.state_dir(),
        api_base_url=services.catalog.api_base_url(),
        open_db=services.catalog.open_db,
        item_id=item_id,
        version=version,
    )


def schedule_backfill(services: Any, config_path: Path) -> None:
    _spawn(backfill_installed(
        config_path=config_path,
        state_dir=services.settings_reader.state_dir(),
        api_base_url=services.catalog.api_base_url(),
        open_db=services.catalog.open_db,
        ledger=services.catalog.ledger,
    ))
