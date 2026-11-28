
import structlog
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable
from pathlib import Path
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import MutableHeaders
from starlette.types import Receive, Scope, Send

from src.core.launch_profiles.agent_resume import ResumePrefixNotApproved
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware

from src.config import settings, StateDirUnavailableError
from src.core.server_log import redact as log_redaction
from src.security_headers import stamp_security_headers
from src.api.account_gates import AccountRequired, account_required_handler
from src.api import mesh_dark, resume_prefix_card
from src.api.peer_route_guard import PeerForwarded, peer_route_guard
from src.api.request_log import RequestLogMiddleware
from src.api.host_guard import HostGuardMiddleware
from src.api.joined_lockdown import JoinedLockdownMiddleware
from src.api.json_gzip import JsonGzipMiddleware
from src.core.boot.catalog import build_registry as build_boot_registry
from src.core.boot.context import BootContext
from src.core.perf_hooks import thread_qos
from src.core.boot.steps import BootRunner
from src.api.shell.pages import router as shell_page_router
from src.api.shell.static import install_static, warm_remaining_static_gzip_cache
from src.core.log_level import expiry as live_log_level_expiry, live as live_log_level
from src.core.version import resolve_version
from src.core.mcp.channel import GRACEFUL_SHUTDOWN_S
from src.core.setup_state import current_exposure, record_bound_host
from src.core.early_listen.ws_deflate import ws_deflate_for
from src.api.setup_routes import router as setup_router, page_router as setup_page_router
from src.api.mcp_routes import router as mcp_router
from src.api.version_routes import router as version_router
from src.api.routes import router as api_router
from src.api.websocket import router as ws_router
from src.api.events_routes import router as events_ws_router
from src.api.browser_socket import router as browser_ws_router
from src.api.auth import limiter as auth_limiter
from src.api.auth_routes import router as auth_router
from src.api.config_files_routes import router as config_files_router
from src.api.session_groups_routes import router as session_groups_router
from src.api.session_group_icon_routes import router as session_group_icon_router
from src.api.session_group_rule_routes import router as session_group_rule_router
from src.api.restart_routes import router as restart_router
from src.api.restore_offer_routes import router as restore_offer_router
from src.api.status_routes import router as status_router
from src.core.phone_link import boot as phone_link_boot
from src.api.attention_routes import router as attention_router
from src.api.preferences_routes import router as preferences_router
from src.api.widget_bars_routes import router as widget_bars_router
from src.api.toast_routes import router as toast_router
try:
    settings.get_state_dir()
except StateDirUnavailableError as exc:
    import sys as _sys

    _banner = f"""
========================================
CLOUDE CODE - STATE DIRECTORY ERROR
========================================

{exc}

The server refuses to start rather than write your session data,
pinned themes, unread flags, or refresh tokens somewhere you did not
choose (or silently drop them in a temp directory that macOS purges on
reboot).

To fix:
1. Make the target directory writable, or
2. Set CLOUDE_STATE_DIR in .env to a writable path, then restart.
========================================
"""
    print(_banner, file=_sys.stderr)
    from src.config.startup_error_log import write_startup_error

    _error_log = write_startup_error(_banner)
    if _error_log is not None:
        print(f"\nError details written to: {_error_log}", file=_sys.stderr)
    _sys.exit(1)

live_log_level.apply_level(live_log_level_expiry.boot_level(
    settings.log_level, Path(settings.auth_config_file).expanduser()
))
structlog.configure(
    processors=[*log_redaction.shared_processors(), structlog.processors.JSONRenderer()],
    wrapper_class=live_log_level.LiveLevelBoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("application_starting", version=resolve_version() or "unknown")
    live_log_level_expiry.arm_at_boot(settings.log_level, Path(settings.auth_config_file).expanduser())
    import asyncio as _asyncio
    from src.core.perf_hooks import executors as _executors

    _executors.configure_default_executor(_asyncio.get_running_loop())
    thread_qos.request_user_interactive("event_loop")
    boot_ctx = BootContext(app=app)
    boot_runner = BootRunner(build_boot_registry())
    await boot_runner.start_all(boot_ctx)

    async def _deferred_static_warm() -> None:
        await _asyncio.sleep(30.0)
        await _executors.run_in(_executors.maintenance_executor(), warm_remaining_static_gzip_cache)

    async def _prewarm_boot_caches() -> None:
        from src.api import themes_routes as _themes_routes

        tasks = [
            _executors.run_in(_executors.maintenance_executor(), _themes_routes.warm_themes_cache),
        ]
        publisher = getattr(app.state, "listing_publisher", None)
        if publisher is not None:
            tasks.append(publisher.run_pass())
        await _asyncio.gather(*tasks, return_exceptions=True)

    from src.core.product_identity import test_mode_enabled as _test_mode_enabled

    _static_warm_task = _asyncio.create_task(_deferred_static_warm(), name="static-gzip-warm")
    _boot_prewarm_task = (
        None if _test_mode_enabled() else _asyncio.create_task(_prewarm_boot_caches(), name="boot-cache-prewarm")
    )

    yield

    if _boot_prewarm_task is not None and not _boot_prewarm_task.done():
        _boot_prewarm_task.cancel()
    if not _static_warm_task.done():
        _static_warm_task.cancel()
    logger.info("application_shutting_down")
    await boot_runner.stop_all(boot_ctx)
    logger.info("application_shutdown_complete")


app = FastAPI(
    title="☁️ Cloud Code",
    description="Remote control and monitoring for Claude Code sessions",
    version=resolve_version() or "unknown",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    dependencies=[Depends(peer_route_guard)],
)
app.add_exception_handler(PeerForwarded, lambda _request, exc: exc.response)
app.add_exception_handler(AccountRequired, account_required_handler)
app.add_exception_handler(ResumePrefixNotApproved, resume_prefix_card.refused)


_VALIDATION_ERROR_KEYS = ("loc", "msg", "type")


def _safe_validation_errors(errors: list) -> list:
    return [
        {key: entry[key] for key in _VALIDATION_ERROR_KEYS if key in entry}
        for entry in errors
        if isinstance(entry, dict)
    ]


@app.exception_handler(RequestValidationError)
async def _validation_error_as_400(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=jsonable_encoder({"detail": _safe_validation_errors(exc.errors())}),
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS allowed origins", origins=settings.allowed_origins)


class SecurityHeadersMiddleware:

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                stamp_security_headers(headers, path, raw_path=scope.get("raw_path") or b"")
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)

app.state.limiter = auth_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIASGIMiddleware)

app.add_middleware(
    HostGuardMiddleware,
    extra_hosts=settings.allowed_hosts_extra,
    allowed_origins=settings.allowed_origins,
)

app.add_middleware(JoinedLockdownMiddleware)

app.add_middleware(JsonGzipMiddleware)

app.add_middleware(RequestLogMiddleware)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(api_router, prefix="/api/v1")
app.include_router(config_files_router, prefix="/api/v1")
app.include_router(version_router, prefix="/api/v1")
phone_link_boot.include_routers(app)
app.include_router(status_router, prefix="/api/v1")
app.include_router(attention_router, prefix="/api/v1")
app.include_router(toast_router, prefix="/api/v1")
app.include_router(preferences_router, prefix="/api/v1")
app.include_router(widget_bars_router, prefix="/api/v1")
app.include_router(session_groups_router, prefix="/api/v1")
app.include_router(session_group_rule_router, prefix="/api/v1")
app.include_router(session_group_icon_router, prefix="/api/v1")
app.include_router(restore_offer_router, prefix="/api/v1")
app.include_router(restart_router, prefix="/api/v1")
app.include_router(setup_router, prefix="/api/v1")
app.include_router(setup_page_router)
app.include_router(mcp_router)
app.include_router(ws_router)
app.include_router(events_ws_router)
app.include_router(browser_ws_router)

install_static(app)
app.include_router(shell_page_router)
mesh_dark.install(app)


if __name__ == "__main__":
    import faulthandler

    import uvicorn

    faulthandler.enable(all_threads=True)

    from src.core.dev_tools.dev_lease import start_watch

    start_watch()

    if settings.dev_reload:
        logger.warning(
            "dev_reload_enabled",
            note=(
                "uvicorn --reload is ON via CLOUDE_DEV_RELOAD=1. This "
                "process will restart itself whenever any watched file "
                "changes, including a git pull. Never set this in a "
                "deployed/production .env."
            ),
        )

    exposure = current_exposure()
    record_bound_host(exposure.bind_host)
    if exposure.locked_down:
        logger.warning(
            "bind_locked_down_pending_setup",
            configured_host=exposure.configured_bind_host,
            effective_host=exposure.bind_host,
            reason=exposure.reason,
        )
    else:
        logger.info(
            "bind_resolved",
            effective_host=exposure.bind_host,
            reason=exposure.reason,
        )

    log_redaction.install_stdlib_routing()

    if settings.dev_reload:
        uvicorn.run(
            "src.main:app",
            host=exposure.bind_host,
            port=settings.port,
            reload=settings.dev_reload,
            log_level="info",
            log_config=None,
            ws_per_message_deflate=ws_deflate_for(exposure.bind_host),
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
        )
    else:
        from src.core.early_listen import serve_early

        serve_early(uvicorn.Config(
            app,
            host=exposure.bind_host,
            port=settings.port,
            log_level="info",
            log_config=None,
            ws_per_message_deflate=ws_deflate_for(exposure.bind_host),
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
        ))
