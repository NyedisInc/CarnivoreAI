
import structlog
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable
from pathlib import Path
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.config import settings, StateDirUnavailableError
from src.core.server_log import redact as log_redaction
from src.security_headers import stamp_security_headers
from src.api.account_gates import AccountRequired, account_required_handler
from src.api.peer_route_guard import PeerForwarded, peer_route_guard
from src.api.request_log import RequestLogMiddleware
from src.api.host_guard import HostGuardMiddleware
from src.api.joined_lockdown import JoinedLockdownMiddleware
from src.api.json_gzip import JsonGzipMiddleware
from src.core.boot.catalog import build_registry as build_boot_registry
from src.core.boot.context import BootContext
from src.core.boot.steps import BootRunner
from src.api.shell.pages import router as shell_page_router
from src.api.shell.static import install_static
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
    boot_ctx = BootContext(app=app)
    boot_runner = BootRunner(build_boot_registry())
    await boot_runner.start_all(boot_ctx)

    yield

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


@app.middleware("http")
async def csp_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    stamp_security_headers(response.headers, request.url.path)
    return response

app.state.limiter = auth_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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


if __name__ == "__main__":
    import faulthandler

    import uvicorn

    faulthandler.enable(all_threads=True)

    from src.core.dev_lease import start_watch

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
            "src.main:app",
            host=exposure.bind_host,
            port=settings.port,
            log_level="info",
            log_config=None,
            ws_per_message_deflate=ws_deflate_for(exposure.bind_host),
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
        ))
