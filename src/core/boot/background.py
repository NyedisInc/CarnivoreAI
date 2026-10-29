
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable, Union

import structlog

from src.api.catalog_required_routes import run_required_pass
from src.config import settings
from src.core import resource_push
from src.core.boot.steps import BootStep, StepFn, teardown_slot
from src.core.boot.teardown import stop_task
from src.core.browsers.manager import BrowserManager
from src.core.catalog import theme_migration
from src.core.catalog.index_refresher import IndexRefresher
from src.core.pipe_prune import PipePruner
from src.core.resource_push import topics as resource_topics
from src.core.skills.auto_update import after_refresh_hook, run_auto_update_pass
from src.core.skills.journal_recovery import recover_pending
from src.core.skills.project_scope import ProjectPathRefused, known_project_roots
from src.core.skills.sweeper import SkillSweeper
from src.core.upload_sweeper import UploadSweeper, datastore_project_paths
from src.cplugs.host.adoption import run_adoption_pass
from src.cplugs.host.catalog_move import run_catalog_move_pass

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()


@dataclass
class _Tasks:

    by_name: dict[str, "asyncio.Task[object]"] = field(default_factory=dict)


def _start_browsers(ctx: "BootContext", tasks: _Tasks) -> None:
    browser_manager = BrowserManager(settings.get_state_dir(), lambda: settings.load_auth_config().browser)
    ctx.app.state.browser_manager = browser_manager
    tasks.by_name["browser_sweep"] = asyncio.create_task(browser_manager.boot_sweep())


async def _stop_browsers(ctx: "BootContext", tasks: _Tasks) -> None:
    await ctx.stop_part("browser_sweep_task", lambda: stop_task(tasks.by_name.get("browser_sweep")))
    await ctx.stop_part("browser_manager", ctx.app.state.browser_manager.aclose)


def _start_upload_sweeper(ctx: "BootContext", tasks: _Tasks) -> None:
    if not ctx.auth_cfg.uploads.enabled:
        return
    from src.core.project_authority import resolve_projects

    cfg = ctx.auth_cfg.uploads
    upload_sweeper = UploadSweeper(
        ttl_seconds=cfg.ttl_seconds,
        interval_seconds=cfg.sweep_interval_seconds,
        project_paths=datastore_project_paths(resolve_projects(settings.get_state_dir())),
        default_dir=settings.get_working_dir(),
        project_paths_provider=lambda: datastore_project_paths(resolve_projects(settings.get_state_dir())),
    )
    ctx.app.state.upload_sweeper = upload_sweeper
    tasks.by_name["upload_sweeper"] = asyncio.create_task(upload_sweeper.run())
    logger.info("upload_sweeper_scheduled", interval_seconds=cfg.sweep_interval_seconds, ttl_seconds=cfg.ttl_seconds)


async def _stop_upload_sweeper(ctx: "BootContext", tasks: _Tasks) -> None:
    task = tasks.by_name.get("upload_sweeper")
    if task is not None:
        await ctx.stop_part("upload_sweeper_task", lambda: stop_task(task))
        logger.info("upload_sweeper_stopped")


def _start_skill_sweeper(ctx: "BootContext", tasks: _Tasks) -> None:

    def _known_projects() -> frozenset:
        try:
            return known_project_roots(settings.get_state_dir())
        except ProjectPathRefused:
            return frozenset()

    skill_sweeper = SkillSweeper(install_roots=ctx.services.install_roots, project_roots=_known_projects)
    ctx.app.state.skill_sweeper = skill_sweeper
    tasks.by_name["skill_sweeper"] = asyncio.create_task(skill_sweeper.run())


async def _stop_skill_sweeper(ctx: "BootContext", tasks: _Tasks) -> None:
    await ctx.stop_part("skill_sweeper_task", lambda: stop_task(tasks.by_name.get("skill_sweeper")))
    logger.info("skill_sweeper_stopped")


def _start_pipe_pruner(ctx: "BootContext", tasks: _Tasks) -> None:
    tasks.by_name["pipe_pruner"] = asyncio.create_task(PipePruner(
        log_dir=settings.get_log_dir(),
        state_dir=settings.get_state_dir(),
        socket_name=ctx.session_manager.tmux_socket_name(),
    ).run())


async def _stop_pipe_pruner(_ctx: "BootContext", tasks: _Tasks) -> None:
    await stop_task(tasks.by_name.get("pipe_pruner"))


def _start_skill_journal(ctx: "BootContext", tasks: _Tasks) -> None:
    services = ctx.services

    async def _recover_skill_updates() -> dict:
        roots = services.install_roots
        try:
            counts = await asyncio.to_thread(recover_pending, roots.pending_dir(), roots)
        except (OSError, ValueError) as exc:
            logger.warning("skill_journal_recovery_failed", error=str(exc))
            return {}
        if any(counts.values()):
            logger.info("skill_journal_recovery", **counts)
            resource_push.notify(resource_topics.THEMES)
        return counts

    theme_migration.prune_retired_pins(services)
    task = asyncio.create_task(_recover_skill_updates())
    tasks.by_name["skill_journal"] = task
    ctx.app.state.skill_journal_recovery = task


async def _stop_skill_journal(_ctx: "BootContext", tasks: _Tasks) -> None:
    await stop_task(tasks.by_name.get("skill_journal"))


def _start_auto_update(ctx: "BootContext", tasks: _Tasks) -> None:
    app = ctx.app
    services = ctx.services
    skill_journal_task = tasks.by_name["skill_journal"]
    auto_update_hook = after_refresh_hook(services)

    async def _after_index_refresh() -> None:
        await auto_update_hook()
        from src.core.pack.skills.wiring import after_index_refresh as _pack_skills_after_refresh

        await _pack_skills_after_refresh()

    services.catalog.index_cache.after_refresh = _after_index_refresh

    async def _boot_auto_update() -> None:
        await asyncio.wait({skill_journal_task})
        await run_required_pass(app)
        await run_adoption_pass(services)
        await run_catalog_move_pass(services, settings.get_state_dir())
        await run_auto_update_pass(services)

    catalog_index_refresher = IndexRefresher(services.catalog.index_cache, services=services)
    catalog_index_refresher.start()
    app.state.catalog_index_refresher = catalog_index_refresher
    app.state.skill_auto_update = asyncio.create_task(_boot_auto_update())


async def _stop_index_refresher(ctx: "BootContext", _tasks: _Tasks) -> None:
    await ctx.app.state.catalog_index_refresher.stop()


def steps() -> list[BootStep]:
    tasks = _Tasks()

    def bind(fn: Callable[["BootContext", _Tasks], Union[None, Awaitable[None]]]) -> StepFn:
        return lambda ctx: fn(ctx, tasks)

    return [
        BootStep(name="browsers", order=360, stop_parts=("browser_sweep_task", "browser_manager"), start=bind(_start_browsers), stop=bind(_stop_browsers),
                 stop_order=teardown_slot(44)),
        BootStep(name="upload_sweeper", order=370, stop_parts=("upload_sweeper_task",), start=bind(_start_upload_sweeper), stop=bind(_stop_upload_sweeper),
                 stop_order=teardown_slot(33)),
        BootStep(name="skill_sweeper", order=380, stop_parts=("skill_sweeper_task",), start=bind(_start_skill_sweeper), stop=bind(_stop_skill_sweeper),
                 stop_order=teardown_slot(36)),
        BootStep(name="pipe_pruner", order=390, stop_name="pipe_pruner_task", start=bind(_start_pipe_pruner), stop=bind(_stop_pipe_pruner),
                 stop_order=teardown_slot(35)),
        BootStep(name="skill_journal_recovery", order=400, stop_name="skill_journal_task", start=bind(_start_skill_journal),
                 stop=bind(_stop_skill_journal), stop_order=teardown_slot(37)),
        BootStep(name="skill_auto_update", order=410, stop_name="catalog_index_refresher", start=bind(_start_auto_update), stop=bind(_stop_index_refresher),
                 stop_order=teardown_slot(23)),
    ]
