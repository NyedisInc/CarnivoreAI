
from __future__ import annotations

from typing import List, Literal, Optional

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.cplugs.save import location_check
from src.cplugs.save.engine import constants as C, scope
from src.cplugs.save.service import RUNTIME
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import health, location, retention
from src.cplugs.sdk.blob_codec import default_codec
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.sdk import transcript_files as tf

logger = structlog.get_logger()

ScopeValue = Literal["human", "human+subsessions", "all"]


class Summary(BaseModel):
    """What the vault holds. ``used_bytes`` is every chunk on disk; ``cap_bytes`` limits HISTORY only (``history_bytes``)."""

    used_bytes: int
    cap_bytes: int
    conversations: int
    points: int
    current_backups: int = Field(0, description="always 0: the vault has no rotating copy; kept for older clients")
    pinned: int
    pinned_bytes: int = 0
    max_points_per_conversation: int
    codec: str
    history_bytes: int = 0
    over_cap: bool = False
    location: str = Field("", description="the stored location, blank for the default")
    root: str = Field("", description="the folder the vault is in now")
    available: bool = True
    error: str = ""
    uncovered: Optional[int] = Field(None, description="conversations on disk with no vault copy; null until the first sweep")
    on_disk: Optional[int] = None


class WarningView(BaseModel):
    """One piece of advice, whole: the same shape the settings save answers with in ``settings_warnings``."""

    code: str
    message: str
    field: str = ""
    detail: str = ""


class LocationView(BaseModel):
    """The vault location in force, and its check (the settings pane shows all of it)."""

    location: str = Field(description="the stored setting; blank means the default under the state folder")
    root: str
    available: bool
    error: str = ""
    setting: str = Field(K.LOCATION_SETTING, description="the plugin setting that holds the location; write it through PUT /api/v1/cplugs/save")
    refusals: List[str] = Field(default_factory=list, description="backup destination rules the stored location breaks (the vault refuses it)")
    warnings: List[WarningView] = Field(default_factory=list, description="advice, never a refusal: the vault shares a disk with the transcripts")


class HealthView(BaseModel):
    """The vault's health facts (see ``vault/health.py``)."""

    known: bool
    uncovered: Optional[int] = None
    on_disk: Optional[int] = None
    stale_hours: Optional[int] = None
    unavailable: Optional[str] = None
    over_cap: bool = False
    damaged: int = 0
    pending: int = 0
    legacy_unmigrated: int = Field(0, description="restore points of the old format that could not be moved into the vault yet; they are retried")


class SettingsBody(BaseModel):
    """The global cap in GB."""

    cap_gb: float = Field(gt=0, le=10000)


class SettingsView(BaseModel):
    """The restore point settings in force right now."""

    cap_gb: float
    cap_env_locked: bool = Field(description=f"true when {C.CAP_ENV_VAR} decides the cap")
    cap_env_var: str


class ScopeView(BaseModel):
    """The capture scope in force and the values it may take."""

    capture_scope: str = Field(description="human | human+subsessions | all")
    default: str = C.DEFAULT_CAPTURE_SCOPE
    choices: List[str] = Field(default_factory=lambda: list(C.CAPTURE_SCOPES))


class ScopeBody(BaseModel):
    """The new capture scope."""

    capture_scope: ScopeValue


def location_now() -> LocationView:
    state = tf.state_dir()
    stored = location.read_location()
    root = location.resolve_root(state)
    problems = location.refusals(stored) if stored else []
    advice = [WarningView(**w.as_wire()) for w in location_check.warnings_for(root)]
    try:
        location.open_root(state)
        return LocationView(location=stored, root=str(root), available=True, refusals=problems, warnings=advice)
    except VaultUnavailable as exc:
        return LocationView(location=stored, root=str(root), available=False, error=str(exc), refusals=problems, warnings=advice)


def summary_now() -> Summary:
    state = tf.state_dir()
    where = location_now()
    record = health.evaluate(health.read(state))
    base = dict(location=where.location, root=where.root, available=where.available, error=where.error,
                uncovered=record["uncovered"], on_disk=record["on_disk"], max_points_per_conversation=K.MAX_POINTS_PER_UNIT,
                codec=default_codec(), cap_bytes=tf.limits.cap_bytes(state))
    if not where.available:
        return Summary(used_bytes=0, conversations=0, points=0, pinned=0, **base)
    vault = RUNTIME.vault()
    saved = retention.read_state(vault.root)
    if "history_bytes" not in saved:
        saved = retention.assess(vault, base["cap_bytes"])
    return Summary(used_bytes=int(saved.get("used_bytes") or 0), conversations=int(saved.get("units") or 0),
                   points=int(saved.get("points") or 0), pinned=int(saved.get("pinned") or 0),
                   history_bytes=int(saved.get("history_bytes") or 0), over_cap=bool(saved.get("over_cap")), **base)


def health_now() -> HealthView:
    return HealthView(**health.evaluate(health.read(tf.state_dir())))


def settings_now() -> SettingsView:
    return SettingsView(cap_gb=tf.limits.cap_bytes(tf.state_dir()) / 1024 ** 3, cap_env_locked=tf.limits.cap_env_locked(),
                        cap_env_var=C.CAP_ENV_VAR)


def apply_cap(cap_gb: float) -> None:
    if tf.limits.cap_env_locked():
        raise HTTPException(status_code=409, detail={"code": "cap_env_locked",
                                                     "detail": f"{C.CAP_ENV_VAR} is set and decides the cap; unset it to change it here"})
    try:
        tf.limits.set_cap_gb(tf.state_dir(), cap_gb)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not save the settings: {exc}")
    try:
        retention.assess(RUNTIME.vault(), lambda: tf.limits.cap_bytes(tf.state_dir()))
    except (VaultUnavailable, OSError) as exc:
        logger.warning("save_cap_reassess_failed", error=str(exc), error_type=type(exc).__name__)


def add_to(router: APIRouter) -> None:

    @router.get("/summary", response_model=Summary)
    async def get_summary() -> Summary:
        """Total size against the cap, and counts."""
        return await run_in_threadpool(summary_now)

    @router.get("/settings", response_model=SettingsView)
    async def get_settings() -> SettingsView:
        """The cap, and whether the environment overrides it."""
        return await run_in_threadpool(settings_now)

    @router.put("/settings", response_model=Summary)
    async def put_settings(body: SettingsBody) -> Summary:
        """Set the global size cap (GB). Lowering it takes effect at the next capture (oldest unpinned points go)."""
        await run_in_threadpool(apply_cap, body.cap_gb)
        return await run_in_threadpool(summary_now)

    @router.get("/location", response_model=LocationView)
    async def get_location() -> LocationView:
        """Where the vault lives, and whether that place can be used now."""
        return await run_in_threadpool(location_now)

    @router.get("/health", response_model=HealthView)
    async def get_health() -> HealthView:
        """Coverage, staleness and availability of the vault."""
        return await run_in_threadpool(health_now)

    @router.get("/capture-scope", response_model=ScopeView)
    async def get_capture_scope() -> ScopeView:
        """The capture scope in force (``human`` when config.json holds none)."""
        return ScopeView(capture_scope=await run_in_threadpool(scope.read_scope))

    @router.put("/capture-scope", response_model=ScopeView)
    async def put_capture_scope(body: ScopeBody) -> ScopeView:
        """Store a new capture scope; it applies from the next capture. 422 bad value or block; 500 unwritable."""
        try:
            value = await run_in_threadpool(scope.set_scope, body.capture_scope)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except OSError as exc:
            logger.error("save_scope_write_failed", error=str(exc), error_type=type(exc).__name__)
            raise HTTPException(status_code=500, detail="could not save the capture scope")
        return ScopeView(capture_scope=value)
