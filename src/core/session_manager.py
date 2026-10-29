
import asyncio
import dataclasses
import hmac
import json
import os
import threading
import base64
import secrets
import shutil
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Mapping, Optional
from datetime import datetime, timezone
from fastapi import HTTPException
import structlog

if TYPE_CHECKING:
    from src.core.session_adopt_identity import AdoptIdentity

from src.config import mcp_launch, settings
from src.models import (
    Session,
    SessionStatus,
    SessionInfo,
    SessionStats,
    LogEntry,
    Toast,
)
from src.core import claude_hooks
from src.core.pipeline import triggers as save_triggers
from src.core.workspace_settings import build_spawn_env
from src.core.account_switch import launch_env, restart_account
from src.core.session_backend import SessionBackend, build_backend
from src.core.scrollback_replay import with_cursor_restore

from src.core.live_ports import LiveSessionRecordStore, LiveSettings
from src.core.sessions.hook_token_authority import HookTokenAuthority
from src.core.sessions.owned_tmux_ledger import OwnedTmuxLedger
from src.core.sessions.pane_listing_cache import invalidate_pane_listing
from src.core.sessions.probe_health import ProbeHealth, ProbeHealthRecorder
from src.core.sessions.registry import SessionRegistry
from src.core.sessions.sidecars import AttachmentSidecars
from src.core.sessions.name_locks import NameLocks
from src.core.sessions.pending_registration import hold_pending_registration
from src.core.sessions import theme_dotfile
from src.core.sessions.theme_accents import ThemeAccents
from src.core.sessions.theme_store import ThemeStore
from src.core.sessions.toast_inbox import ToastInbox
from src.core.sessions import remote_sessions
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import is_remote_backend, parse_remote_session_id
from src.cplugs.sdk import turn_events
from src.core.hosts.registry import HostRegistry
from src.core.db_models import SESSION_CLAUDE_UUID_SOURCE_HOOK
from src.core.product_identity import ENV_PREFIX
from src.core.tmux_listing import TmuxListing, coerce_listing
from src.core.launch_profiles import create_seam, restart_seam
from src.core.launch_profiles.launched_with import launched_with_for_row
from src.core.launch_record import launch_record
from src.core.agent_family_display import resolve_family_for_display
from src.core.agent_wrapper_display import resolve_wrapper_for_display
from src.core.session_agent_evidence import (
    choose_agent_evidence,
    recorded_launch_family,
)
from src.core.session_theme_resolution import resolve_theme
from src.core import listing_gather
from src.core.db_reuse.core_read import lend_for_state_dir
from src.core.sessions.listing_connection import lend_name_read_connection
from src.core import session_ghost_reap, session_name_claim, session_sleep
from src.core.pack.identity import home as project_home
from src.core.session_name_claim import sanitize_tmux_name as _sanitize_tmux_name  # noqa: F401
from src.core.listing_prefetch import ListingPrefetch
from src.core.session_token_usage.listing_model_facts import ModelListingFacts
from src.core import session_agent_infer_apply
from src.core.session_agent_infer import restart_agent_type
from src.core.session_agent_infer_resweep import AgentResweep
from src.core.session_status import (
    LIVENESS_GONE,
    LIVENESS_LIVE,
    LIVENESS_UNKNOWN,
    STATUS_DEAD,
    STATUS_UNKNOWN,
    derive_read_state,
    resolve_listing_liveness,
)
from src.core.session_activity import (
    EVENT_STOP,
    SessionActivityTracker,
    map_tmux_fallback,
)
from src.core.session_status_map import (
    StatusMap,
    listing_proves_alive,
    status_map_from_listing,
)
from src.core.attention.startup_screen import gate_with_screen
from src.core.session_startup_gate import (
    GATE_UNKNOWN,
    detect_startup_prompt,
    resolve_startup_gate,
)
from src.core.session_startup_gate_ledger import (
    StartupGateLedger,
    capture_pane_tail,
)
from src.core import unread_follow_up, unread_identity
from src.core.sessions import startup_tail_prefetch
from src.core import session_view_clears
from src.core import toast_auto_ack
from src.core.bounded_stream import OFFER_ACCEPTED, OFFER_OVERFLOWED
from src.core import session_permission_verify_apply
from src.core import listing_attention
from src.core.attention.display import activity_hint_for, status_source_for, to_display
from src.core.unread_store import UnreadStore
from src.core.unique_tmp_path import unique_tmp_path
from src.core.upload_sweeper import (
    SweepOutcome,
    UploadSweeper,
    datastore_project_paths,
    sweep_verdict,
)
from src.utils.pty_session import PTYSessionError
from src.utils.template_manager import copy_templates as copy_template_files

from src.core.sessions.owned_tmux_ledger import DB_INSTANCES_UNSET

logger = structlog.get_logger()


def _record_stats_event(kind: str, subject: str) -> None:
    try:
        from src.core.stats import events
        events.record_soon(kind, subject)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stats_event_hook_failed", kind=kind, error_type=type(exc).__name__)

_TERMINAL_COMMAND_WRITE_ATTEMPTS = 20
_TERMINAL_COMMAND_WRITE_DELAY_SECONDS = 0.1

WORK_STAMP_MIN_INTERVAL_SECONDS = 15.0




def backfill_agent_type(
    session: Optional[Session],
    owned_tmux_sessions: Optional[set] = None,
) -> int:
    if session is None or session.agent_type is not None:
        return 0

    is_adopted = session.id.startswith("adopted:")
    if is_adopted:
        return 0

    session.agent_type = "claude"
    return 1


def _configured_wrappers():
    """The user's configured launch wrappers, or an empty list.

    Description: THE ONE PLACE this is read for display resolution, and it
      exists because the previous spelling was wrong everywhere and could
      not fail. Three call sites used::

          getattr(getattr(settings, "agents", None), "wrappers", None) or []

      ``Settings`` has no ``agents`` attribute - the agents block lives on
      ``settings.load_auth_config().agents`` - so that chain returned None,
      then ``or []``, on every machine, forever. The defensive getattr
      turned a WRONG ATTRIBUTE PATH into a plausible empty answer instead
      of an AttributeError, and an empty wrapper list is not obviously
      wrong: ``resolve_family_for_display`` simply could not match any
      wrapper id, so every session launched through a wrapper rendered
      "unknown family". The session we knew the most about displayed worse
      than one we had only fingerprinted.

      The defensiveness that matters is kept - a config that will not load
      must not break a listing - but it is now around the IO, not around a
      misspelled path.
    Output: list - AgentWrapper objects; empty only when the config truly
      has none or could not be read.
    Example: _configured_wrappers()
    """
    try:
        return settings.load_auth_config().agents.wrappers or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("configured_wrappers_unavailable", error=str(exc))
        return []



SHARED_STATUS_MAP_MAX_AGE_SECONDS = 1.0


class SessionManager:

    _borrowed = threading.local()

    def __init__(
        self,
        *,
        probe_health: Optional[ProbeHealthRecorder] = None,
        theme_store: Optional[ThemeStore] = None,
        toast_inbox: Optional[ToastInbox] = None,
        registry: Optional[SessionRegistry] = None,
        sidecars: Optional[AttachmentSidecars] = None,
        owned_tmux: Optional[OwnedTmuxLedger] = None,
        hook_tokens: Optional[HookTokenAuthority] = None,
        adopt_locks: Optional[NameLocks] = None,
    ):
        self._probe_health: ProbeHealthRecorder = (
            probe_health if probe_health is not None else ProbeHealthRecorder()
        )
        self._resolved_legacy_probe_socket: Optional[str] = None
        self._published_status_map: Optional[tuple[float, StatusMap]] = None
        self._theme_store: ThemeStore = (
            theme_store
            if theme_store is not None
            else ThemeStore(pin_path=lambda: settings.get_pinned_themes_path())
        )
        self._toast_inbox: ToastInbox = (
            toast_inbox if toast_inbox is not None else ToastInbox()
        )
        self._registry: SessionRegistry = (
            registry
            if registry is not None
            else SessionRegistry(log_cap=lambda: settings.log_buffer_size)
        )
        self._sidecars: AttachmentSidecars = (
            sidecars if sidecars is not None else AttachmentSidecars()
        )
        self._adopt_locks = adopt_locks if adopt_locks is not None else NameLocks()
        self._notification_policy_store = None

        self._owned: OwnedTmuxLedger = (
            owned_tmux
            if owned_tmux is not None
            else OwnedTmuxLedger(
                metadata_path=lambda: settings.get_session_metadata_path(),
                records=LiveSessionRecordStore(settings_reader=LiveSettings()),
                socket_name=self._tmux_socket_name,
            )
        )


        self._boot_readopt_task = None
        self._instance_epochs: dict[str, int] = {}
        self.hosts = HostRegistry(self._datastore_connection)
        self._last_persisted_activity: dict[tuple, str] = {}
        self._last_work_stamp_at: dict[str, float] = {}
        self._last_session_end_uuid: dict[str, str] = {}
        self.hook_tokens: HookTokenAuthority = (
            hook_tokens
            if hook_tokens is not None
            else HookTokenAuthority(
                lambda: settings.get_state_dir(),
                on_drop=lambda sid: self._instance_epochs.pop(sid, None),
            )
        )
        self._pending_agent_registration: dict[str, tuple[str, asyncio.Event]] = {}


        self._activity_tracker = SessionActivityTracker()

        self._startup_gate_ledger = StartupGateLedger()

        self._unread_store = UnreadStore(settings.get_unread_state_path())
        self._unread_rows: dict[str, int] = {}
        self._unread_epochs: dict[str, int] = {}

        self._attention_watcher = None
        self._fresh_evidence = None
        self._agent_resweep = AgentResweep()

        self._listing_fingerprint_cache: dict[
            tuple[str, str, int], Optional[str]
        ] = {}

        self._load_session_metadata()
        self._theme_store.load()



    @property
    def adopt_fifo_start_offset(self) -> Optional[int]:
        sess = self._registry.current_session()
        if sess is None:
            return None
        return self._sidecars.peek_fifo_offset(sess.id)


    def _make_output_handler(
        self, session_id: str
    ) -> Callable[[bytes], Awaitable[None]]:
        def _on_output(data: bytes) -> None:
            self._registry.publish(session_id, data)
        return _on_output

    def _make_viewer_probe(self, session_id: str) -> Callable[[], bool]:
        def _has_viewers() -> bool:
            return bool(self._registry.subscribers.get(session_id))
        return _has_viewers

    def _wipe_session_state(self, session_id: str) -> None:
        wiped_backend = self._registry.get_backend(session_id)
        self._startup_gate_ledger.forget(
            getattr(wiped_backend, "tmux_session", None)
        )
        self._registry.forget(session_id)
        self._sidecars.forget(session_id)
        self._toast_inbox.drop_session(session_id)
        self._activity_tracker.forget(session_id)
        if self._registry.last_session_id == session_id:
            self._registry.last_session_id = (
                next(reversed(self._registry.sessions)) if self._registry.sessions else None
            )
        turn_events.publish_turn_end(session_id)


    def attach_notification_policy_store(self, store) -> None:
        self._notification_policy_store = store

    def notification_policy_for(self, session_id: str):
        from src.core.session_notification_policy import UNKNOWN_VERDICT

        store = getattr(self, "_notification_policy_store", None)
        if store is None:
            return UNKNOWN_VERDICT
        sess = self._registry.sessions.get(session_id)
        tmux_name = getattr(sess, "tmux_session", None) if sess else None
        return store.for_instance(
            tmux_name, self._instance_epochs.get(session_id)
        )

    def notification_policy_for_uuid(self, session_uuid: str):
        from src.core.session_notification_policy import UNKNOWN_VERDICT

        store = getattr(self, "_notification_policy_store", None)
        return UNKNOWN_VERDICT if store is None else store.for_uuid(session_uuid)

    def notification_policy_stamp(self, session_id: str):
        """The verdict to STAMP on an outgoing notification, or None.

        Description: the difference from :meth:`notification_policy_for`
            is the no-store case, and it is not a detail. No policy store
            attached means this build has no durable mute wired in at all,
            so there is nothing to honour and an event must go out exactly
            as it did before mute existed - which is what None asks the
            producer to do. A store that IS attached but could not be read
            returns ``unknown``, and the dispatcher refuses that: not
            having looked is not permission to push.
        """
        if getattr(self, "_notification_policy_store", None) is None:
            return None
        return self.notification_policy_for(session_id)








    def _adopt_identity_for(
        self, name: str, epoch: Optional[int]
    ) -> "AdoptIdentity":
        from src.core.session_adopt_identity import resolve_adopt_identity
        from src.core.session_store import get_instance

        conn = self._datastore_connection()
        socket = self._tmux_socket_name()
        try:
            def _lookup(row_name: str, row_epoch: Optional[int]):
                if conn is None:
                    return None
                return get_instance(
                    conn, socket=socket, name=row_name, epoch=row_epoch
                )

            return resolve_adopt_identity(
                name=name,
                epoch=epoch,
                row_lookup=_lookup,
                hook_names=dict(self.hook_tokens.tmux_names or {}),
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error as exc:
                    logger.debug("adopt_identity_conn_close_failed", error=str(exc))

    def get_env_for_spawn(self, session_id: str) -> dict[str, str]:
        """Return the env-var trio injected into the spawned agent's tmux env.

        Minted lazily on first call so backends that ``start()`` BEFORE the
        session is fully registered (we don't - see ``create_session``) can
        still ask. Empty dict when the configured port can't be read.

        Layering (feat/settings-gui): the user's global workspace
        environment goes in FIRST, then ``development_root`` as
        ``CLOUDE_DEV_ROOT`` and ``default_shell`` as ``SHELL``, then the
        three app variables below LAST so they win unconditionally. See
        ``src/core/workspace_settings.build_spawn_env`` - precedence is
        expressed as write order rather than trusted to the name policy,
        so the control channel stays intact even if that policy is later
        loosened.

        This reaches only NEWLY spawned terminals. tmux copies the
        environment at ``new-session`` time; a session already running
        keeps the environment it was born with, and the settings screen
        says so rather than letting the user believe a save applied
        everywhere.

        Variables (legacy -> current twin):
            CLOUDECODE_SESSION_ID / CARNIVORE_SESSION_ID - the
                ``X-Cloudecode-Session`` header so the hook endpoint routes
                the POST to the right session's toast bucket.
            CLOUDECODE_HOOK_TOKEN / CARNIVORE_HOOK_TOKEN - bearer credential
                for that endpoint, validated via ``HookTokenAuthority.validate``.
            CLOUDECODE_HOOK_URL / CARNIVORE_HOOK_URL - loopback URL the hook
                curl POSTs to, built from ``settings.port``.
        """
        token = self.hook_tokens.token_for_spawn(session_id)
        try:
            port = settings.port
        except Exception:
            return {}
        hook_url = f"http://127.0.0.1:{port}/api/v1/hooks/claude-event"
        app_env = {
            "CLOUDECODE_SESSION_ID": session_id,
            "CLOUDECODE_HOOK_TOKEN": token,
            "CLOUDECODE_HOOK_URL": hook_url,
            f"{ENV_PREFIX}SESSION_ID": session_id,
            f"{ENV_PREFIX}HOOK_TOKEN": token,
            f"{ENV_PREFIX}HOOK_URL": hook_url, **mcp_launch.spawn_env(port),
        }

        try:
            local_host = settings.load_auth_config().providers.local_host
        except Exception:  # noqa: BLE001
            local_host = ""
        if local_host:
            app_env["CLDL_HOST"] = local_host

        try:
            workspace = settings.load_auth_config().workspace.model_dump()
        except Exception as exc:  # noqa: BLE001
            logger.warning("workspace_env_unavailable", error=str(exc))
            return app_env
        return build_spawn_env(workspace, app_env)


    @property
    def backend_name(self) -> str:
        backend = self._registry.current_backend()
        if backend is None:
            return "none"
        cls = backend.__class__.__name__
        return cls.replace("Backend", "").lower()


    async def lifespan_startup(self) -> None:
        """Called once on server startup to re-adopt a surviving tmux session.

        This is separate from `__init__` because it needs to be awaitable and
        is driven by the FastAPI lifespan context manager. `main.py` calls
        this after `SessionManager()` is constructed.

        Behavior:
        - Build a probe backend using the metadata slug (if any).
        - Ask it to `discover_existing()`.
        - Reconcile ``owned_tmux_sessions`` against the live listing -
          prune entries whose tmux session no longer exists. Prevents
          indefinite growth from orphaned records after crashes.
        - If the metadata's slug is present in the discovered list AND
          (new-schema case) is in ``owned_tmux_sessions`` OR (legacy
          case) the backfill flag is set, re-register the session as
          active and start the backend's read loop.
        - On first successful rehydrate of legacy metadata, add the
          slug to the owned set and re-persist so subsequent boots use
          the new schema directly.
        - Log other discovered sessions and leave them alone (orphan
          cleanup is out of scope - a v2 ``cloude-cleanup`` script).

        After tmux reconciliation, runs a one-shot orphan sweep of
        ``.cloude_uploads/`` buckets to catch files left by force-killed
        previous runs where ``destroy_session()`` never ran. Wrapped in
        ``try/finally`` so the sweep fires regardless of which
        reconciliation branch exited.
        """
        try:
            await self._lifespan_tmux_reconcile()
        finally:
            self._schedule_boot_readopt()
            remote_sessions.schedule_remote_readopt(self)
            await self._sweep_orphan_uploads()

    def _schedule_boot_readopt(self):
        from src.core.session_boot_readopt import schedule_boot_readopt

        if self._owned.boot_listing is None:
            return None
        return schedule_boot_readopt(self)

    async def _lifespan_tmux_reconcile(self) -> None:
        persisted = self._registry.current_session()
        backfilled = backfill_agent_type(persisted, self._owned.names)
        if backfilled:
            self._save_session_metadata()
            logger.info(
                "session_metadata_agent_type_backfilled",
                count=backfilled,
            )

        probe = build_backend(
            settings,
            session_id="__probe__",
            working_dir=Path.home(),
            on_output=None,
        )
        # could not
        listing = coerce_listing(probe.discover_existing())
        if not listing.ok:
            logger.warning(
                "lifespan_tmux_probe_unavailable",
                reason=listing.reason,
                detail=listing.detail,
                owned_count=len(self._owned.names),
                note=(
                    "tmux could not be enumerated - skipping ownership, "
                    "pinned-theme and unread pruning, and skipping "
                    "rehydrate. No persisted state was changed."
                ),
            )
            return
        tmux_alive = set(listing.names)

        self._owned.boot_listing = listing

        if self._owned.names:
            stale = self._owned.names - tmux_alive
            if stale:
                logger.info(
                    "owned_tmux_sessions_pruning_stale",
                    stale=sorted(stale),
                )
                self._owned.names -= stale
                if persisted is not None:
                    self._save_session_metadata()


        self._unread_store.prune(tmux_alive)

        if persisted is None:
            if tmux_alive:
                logger.info(
                    "session_backend_discovered_orphans",
                    count=len(tmux_alive),
                    names=sorted(tmux_alive),
                    hint="no metadata on disk - leaving orphans alone",
                )
            return

        work_path = Path(persisted.working_dir)
        backend = build_backend(
            settings,
            session_id=persisted.id,
            working_dir=work_path,
            on_output=self._make_output_handler(persisted.id),
            viewer_probe=self._make_viewer_probe(persisted.id),
            session_name=persisted.tmux_session or None,
        )

        if not tmux_alive:
            logger.info(
                "session_metadata_has_no_backend_match",
                session_id=persisted.id,
            )
            self._clear_stale_metadata(persisted.id)
            return

        target_name = getattr(backend, "tmux_session", None)

        ownership_ok = (
            target_name is not None
            and (
                self._owned.is_owned_name(target_name)
                or self._owned.needs_legacy_backfill
            )
        )

        if target_name and target_name in tmux_alive and ownership_ok:
            try:
                await backend.attach_existing()
            except NotImplementedError:
                logger.warning(
                    "session_backend_cannot_rehydrate",
                    session_id=persisted.id,
                    backend=type(backend).__name__,
                )
                self._clear_stale_metadata(persisted.id)
                return
            except RuntimeError as e:
                logger.warning(
                    "session_backend_attach_failed",
                    session_id=persisted.id,
                    error=str(e),
                )
                self._clear_stale_metadata(persisted.id)
                return

            persisted.status = SessionStatus.RUNNING
            self._registry.register(persisted, backend)

            if self._owned.needs_legacy_backfill:
                self._owned.names.add(target_name)
                self._save_session_metadata()
                logger.info(
                    "session_metadata_legacy_backfilled",
                    session_id=persisted.id,
                    owned=sorted(self._owned.names),
                )

            logger.info(
                "session_re_registered_from_backend",
                session_id=persisted.id,
                backend_session=target_name,
            )
            orphans = [n for n in tmux_alive if n != target_name]
            if orphans:
                logger.info(
                    "session_backend_orphans_ignored", names=sorted(orphans)
                )
        else:
            if target_name and target_name in tmux_alive and not ownership_ok:
                logger.warning(
                    "session_metadata_slug_not_owned",
                    session_id=persisted.id,
                    target=target_name,
                    owned=sorted(self._owned.names),
                    note="not rehydrating a non-owned session",
                )
            else:
                logger.warning(
                    "session_metadata_slug_not_in_backend",
                    session_id=persisted.id,
                    target=target_name,
                    discovered=sorted(tmux_alive),
                )
            self._clear_stale_metadata(persisted.id)

    def _clear_stale_metadata(self, session_id: Optional[str] = None) -> None:
        self._owned.drop_session_pointer()
        sid = session_id
        if sid is None:
            cur = self._registry.current_session()
            sid = cur.id if cur is not None else None
        if sid is not None:
            self._wipe_session_state(sid)

    async def _sweep_orphan_uploads(self) -> None:
        from src.core.project_authority import resolve_projects

        auth_cfg = settings.load_auth_config()
        cfg = auth_cfg.uploads
        if not cfg.enabled:
            return
        sweeper = UploadSweeper(
            ttl_seconds=cfg.ttl_seconds,
            interval_seconds=0,
            # could not
            # nothing at all
            # could not
            project_paths=datastore_project_paths(
                resolve_projects(settings.get_state_dir())
            ),
            default_dir=settings.get_working_dir(),
        )
        try:
            result = await sweeper.sweep_now()
            logger.info("upload_orphan_sweep_complete", **result)
        except Exception as exc:
            logger.warning("upload_orphan_sweep_failed", error=str(exc))


    def _load_session_metadata(self):
        load = self._owned.load()
        if load.session is None:
            return

        try:
            loaded = Session(**load.session)
        except (TypeError, ValueError) as exc:
            logger.error("failed_to_load_session_metadata", error=str(exc))
            return

        self._registry.register(loaded, backend=None)
        logger.info(
            "session_metadata_loaded",
            session_id=loaded.id,
            owned_count=load.owned_count,
            note="probe deferred to lifespan_startup",
        )

    def _save_session_metadata(self, session: Optional[Session] = None):
        sess = session or self._registry.current_session()
        if not sess or is_remote_backend(self._registry.backends.get(sess.id)):
            return
        self._owned.save(sess.model_dump())


    def _is_unread(
        self, tmux_name: Optional[str], epoch: Optional[int] = None,
        row_id: Optional[int] = None,
    ) -> bool:
        return unread_follow_up.is_unread(self, tmux_name, epoch, row_id)

    def _unread_epoch(self, tmux_name: Optional[str]) -> Optional[int]:
        """The epoch THIS session's unread flag keys on. One source, always.

        Description: delegates to ``src/core/unread_identity.py``, which
            is the only thing in this file allowed to answer the question
            - the manual control, the ``Stop`` writer and the
            viewed-clear all call THIS, so a clear can never land on a
            key the set did not write. It reads a tmux measurement (memo
            first, one listing on a miss) and refuses the two answers
            that used to compete with it: the database row's recorded
            epoch and the session_id-keyed ``_instance_epochs``.

            NEVER CALL THIS FROM INSIDE ``list_attachable_sessions``: the
            probe it may spend asks that method for the listing, so a
            call from within its own loop re-enters it. That loop already
            carries ``created_at_epoch`` on each row and calls
            ``unread_identity.remember`` instead.
        Inputs:
            tmux_name: literal tmux session name, or None.
        Output: int | None - None when tmux could not answer, which the
            store treats as an unmeasured instance (the legacy bare-name
            key) rather than as a new one.
        """
        return unread_identity.resolve_epoch(
            self._unread_epochs,
            tmux_name,
            lambda: coerce_listing(self.list_attachable_sessions()),
        )

    def mark_session_viewed(self, session_id: str) -> None:
        session_view_clears.clear_on_view(self, session_id=session_id)

    def set_manual_unread(self, tmux_name: str, unread: bool) -> None:
        if not tmux_name:
            raise ValueError("tmux_name is required")
        if unread:
            unread_follow_up.mark(self, tmux_name)
        else:
            session_view_clears.clear_view_state(self, tmux_name=tmux_name)

    def set_pinned_theme(
        self, tmux_name: str, theme_id: Optional[str]
    ) -> None:
        if not self._theme_store.set_pin(tmux_name, theme_id):
            return

        for sid, backend in list(self._registry.backends.items()):
            if getattr(backend, "tmux_session", None) == tmux_name \
                    and not is_remote_backend(backend):
                sess = self._registry.sessions.get(sid)
                if sess is not None:
                    sess.pinned_theme = theme_id
                    self._save_session_metadata(sess)
                break


    @staticmethod
    def _project_theme_path(working_dir) -> Optional[Path]:
        return theme_dotfile.project_theme_path(working_dir)


    @staticmethod
    def _themes_dir() -> Path:
        return ThemeAccents.themes_dir()

    def _get_session_accent_color(
        self, session: Optional[Session]
    ) -> Optional[str]:
        if session is None:
            return None
        return self._theme_store.accent_for(
            getattr(session, "working_dir", None),
            getattr(session, "tmux_session", None),
        )

    def _live_session_id_for_stale_id(self, session_id: str) -> Optional[str]:
        tmux_name = self.hook_tokens.name_for(session_id)
        if not tmux_name:
            return None
        for live_id, sess in self._registry.sessions.items():
            if getattr(sess, "tmux_session", None) != tmux_name:
                continue
            if live_id == session_id:
                continue
            logger.info(
                "toast_session_id_remapped",
                stale_id=session_id,
                live_id=live_id,
                tmux_name=tmux_name,
            )
            return live_id
        return None

    def record_toast(
        self,
        session_id: str,
        kind: str,
        title: str,
        body: Optional[str] = None,
        *,
        notify_type: Optional[str] = None,
    ) -> Toast:
        session = self._registry.sessions.get(session_id)
        if session is None:
            # CLOUDECODE_SESSION_ID
            remapped = self._live_session_id_for_stale_id(session_id)
            if remapped is not None:
                session_id = remapped
                session = self._registry.sessions.get(session_id)
        if session is None:
            raise ValueError(f"Unknown session_id: {session_id!r}")

        color = self._get_session_accent_color(session)
        session_name = getattr(session, "tmux_session", None)
        try:
            session_label = self._label_for_tmux_name(session_name)
        except Exception as exc:
            logger.debug("toast_label_read_threw", error=str(exc))
            session_label = None
        toast, _superseded = self._toast_inbox.store(
            session_id,
            kind=kind,
            title=title,
            body=body,
            color=color,
            session_label=session_label,
            session_name=session_name,
            notify_type=notify_type,
        )

        from src.core.notifications.sources import toast as toast_source

        toast_source.emit_event(self, toast)

        return toast

    def _persist_work_stamp(
        self,
        session_id: str,
        tmux_name: Optional[str],
        kind: Optional[str],
        *,
        at: Optional[str] = None,
        throttle_key: Optional[str] = None,
    ) -> bool:
        if not tmux_name:
            return False
        if kind is not None and kind not in claude_hooks.WORK_EVENTS:
            return False
        key = throttle_key or session_id
        last = self._last_work_stamp_at.get(key)
        stamped_at = time.monotonic()
        if last is not None and (stamped_at - last) < WORK_STAMP_MIN_INTERVAL_SECONDS:
            return False
        self._last_work_stamp_at[key] = stamped_at
        epoch = self._work_stamp_epoch(session_id, tmux_name)
        if epoch is None:
            return True
        from src.core.session_work_stamp import persist_instance_stamp

        persist_instance_stamp(
            self._writable_datastore_connection,
            session_id,
            tmux_name,
            tmux_socket=self._tmux_socket_name(),
            tmux_created_epoch=epoch,
            at=at,
        )
        return True

    def _work_stamp_epoch(
        self, session_id: str, tmux_name: str
    ) -> Optional[int]:
        cached = self._instance_epochs.get(session_id)
        if cached is not None:
            return cached
        try:
            listing = coerce_listing(self.list_attachable_sessions())
            if not listing.ok:
                return None
            for row in listing.sessions:
                if row.get("name") != tmux_name:
                    continue
                epoch = row.get("created_at_epoch")
                if epoch is None:
                    return None
                self._instance_epochs[session_id] = int(epoch)
                return int(epoch)
        except Exception as exc:  # noqa: BLE001
            logger.debug("work_stamp_epoch_probe_failed", error=str(exc))
        return None

    def _persist_settled_activity_state(
        self,
        tmux_name: Optional[str],
        state: Optional[str],
        tmux_created_epoch: Optional[int],
    ) -> None:
        from src.core.session_status import STATUS_UNKNOWN

        if not tmux_name or not state or state == STATUS_UNKNOWN:
            return
        state = derive_read_state(state, unread=False)
        cache_key = (tmux_name, tmux_created_epoch)
        if self._last_persisted_activity.get(cache_key) == state:
            return
        conn = None
        try:
            from src.core.activity_persist import write_state
            from src.core.db import transaction

            conn = self._writable_datastore_connection()
            if conn is None:
                return
            with transaction(conn):
                if write_state(
                    conn,
                    tmux_name,
                    state,
                    tmux_created_epoch,
                    tmux_socket=self._tmux_socket_name(),
                ):
                    self._last_persisted_activity[cache_key] = state
        except Exception as exc:  # noqa: BLE001
            logger.debug("settled_activity_persist_failed", error=str(exc))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def auto_ack_toasts(
        self,
        session_id: str,
        event_kind: str,
        cutoff: Optional[datetime] = None,
    ) -> list[str]:
        if not toast_auto_ack.kinds_answered_by(event_kind):
            return []
        if self._registry.get_session(session_id) is None:
            remapped = self._live_session_id_for_stale_id(session_id)
            if remapped is not None:
                session_id = remapped
        bucket = self._toast_inbox.bucket(session_id)
        if not bucket:
            return []
        candidates = toast_auto_ack.resolve_auto_acks(
            bucket, event_kind, cutoff=cutoff
        )
        changed = [
            toast_id
            for toast_id in candidates
            if self._toast_inbox.ack(
                session_id, toast_id, toast_auto_ack.ACK_REASON_ANSWERED
            )
        ]
        if changed:
            logger.info(
                "toast_auto_acked",
                session_id=session_id,
                **toast_auto_ack.describe(event_kind, changed),
            )
        return changed




    async def flush_pending_login(self, session_id: str) -> str:
        """Type this session's pending provider login, once, on attach.

        Description: the sidecar holds an ACCOUNT ID, the
          row is resolved against ``config.json`` server side, the text
          is written through the SAME ``SessionBackend.write()`` a real
          keystroke takes, and nothing is exec'd, shell-``-c``-ed or
          eval'd anywhere on the path. It fires ON ATTACH for the same
          reason: the WS handshake's resize and repaint clears anything
          typed before it, so a line typed at create time runs into a
          screen the user never sees.

          Pops the id FIRST, so a reconnect never retypes the login.
          The work is in ``src/core/provider_ledger/login_flush.py``,
          because this file is past the 500-line guideline and must not
          grow.
        Inputs: session_id (str) - the session being attached to.
        Output: str - ``none`` (nothing pending, the row is gone, the
          config could not be read, or there is no backend), ``issued``
          (the bytes were written) or ``failed`` (every write raised).
          ``failed`` and ``none`` never collapse: the readiness message
          carries this word to the user.
        Example: outcome = await sm.flush_pending_login("ses_1")
        """
        account_id = self._sidecars.take_pending_login(session_id)
        device_auth = self._sidecars.take_pending_login_device(session_id)
        if not account_id:
            return "none"

        from src.core.provider_ledger import login_flush

        try:
            accounts = settings.load_auth_config().provider_accounts.accounts
        except (OSError, ValueError) as exc:
            logger.warning(
                "provider_login_accounts_unreadable",
                session_id=session_id,
                account_id=account_id,
                error=str(exc),
            )
            return "none"

        account = login_flush.find_account(accounts, account_id)
        if account is None:
            return "none"
        backend = self._registry.backends.get(session_id)
        if backend is None:
            return "none"

        return await login_flush.type_login_command(
            session_id=session_id,
            account=account,
            backend=backend,
            attempts=_TERMINAL_COMMAND_WRITE_ATTEMPTS,
            delay_seconds=_TERMINAL_COMMAND_WRITE_DELAY_SECONDS,
            device_auth=device_auth,
        )

    async def create_session(
        self,
        session_id: str,
        working_dir: Optional[str] = None,
        auto_start_claude: bool = True,
        copy_templates: bool = False,
        initial_cols: Optional[int] = None,
        initial_rows: Optional[int] = None,
        project_name: Optional[str] = None,
        agent_type: Optional[str] = None,
        model: Optional[str] = None,
        agent_extra_args: Optional[List[str]] = None,
        label: Optional[str] = None,
        reuse_session_id: Optional[int] = None,
        extra_env: Optional[Mapping[str, str]] = None,
        host_key: str = LOCAL_HOST_KEY,
        claude_account: Optional[str] = None,
    ) -> Session:
        if host_key != LOCAL_HOST_KEY:
            return await remote_sessions.create_remote_session(
                self, host_key=host_key, session_id=session_id, working_dir=working_dir,
                auto_start=auto_start_claude, initial_cols=initial_cols,
                initial_rows=initial_rows, agent_type=agent_type, label=label,
                base_name=session_name_claim.base_name_for_project(project_name),
                agent_extra_args=agent_extra_args,
                unsupported={"copy_templates": copy_templates, "model": model,
                             "reuse_session_id": reuse_session_id, "extra_env": extra_env})
        await project_home.require_active(working_dir)
        if session_id in self._registry.sessions and (
            session_id not in self._registry.backends
            or not self._registry.backends[session_id].is_alive()
        ):
            logger.info("cleaning_up_zombie_session", session_id=session_id)
            self._wipe_session_state(session_id)

        resolved_agent_type: Optional[str] = agent_type
        if not resolved_agent_type and project_name:
            try:
                from src.api import projects_service

                resolved_agent_type = projects_service.agent_type_for(
                    settings, project_name
                )
            except Exception:
                resolved_agent_type = None
        if not resolved_agent_type:
            resolved_agent_type = "claude"

        if working_dir:
            work_path = Path(working_dir).expanduser()
        else:
            work_path = settings.get_working_dir() / session_id
            logger.warning(
                "session_working_dir_fallback_generated",
                session_id=session_id,
                working_dir=str(work_path),
                reason="no working_dir or project_parent_dir supplied",
            )

        work_path.mkdir(parents=True, exist_ok=True)

        logger.info(
            "creating_session",
            session_id=session_id,
            working_dir=str(work_path),
            copy_templates=copy_templates
        )

        if copy_templates:
            try:
                auth_config = settings.load_auth_config()
                if auth_config.template_path:
                    success, error = copy_template_files(
                        auth_config.template_path,
                        str(work_path)
                    )
                    if success:
                        logger.info("templates_copied_to_session", path=str(work_path))
                    else:
                        logger.warning("template_copy_failed", error=error)
                else:
                    logger.warning("no_template_path_configured")
            except Exception as e:
                logger.error("template_copy_error", error=str(e))

        tmux_session_name = session_name_claim.base_name_for_project(project_name)

        if tmux_session_name:
            claim = session_name_claim.claim_tmux_name(
                tmux_session_name,
                listing=session_name_claim.probe_collision_listing(
                    lambda: build_backend(
                        settings,
                        session_id="__collision_probe__",
                        working_dir=Path.home(),
                        on_output=None,
                    )
                ),
                active_names=self.active_tmux_names(),
                owned_names=session_sleep.reserved_names(self._owned.names),
                recreate=reuse_session_id is not None,
            )
            if claim.reclaimed:
                for stale_id in self._registry.registered_ids_for_tmux_name(
                    claim.name
                ):
                    await session_ghost_reap.drop_registration(
                        self, stale_id, reason="recreate_reclaims_name",
                        tmux_name=claim.name, release_token=True,
                    )
                logger.info(
                    "session_create_name_reclaimed",
                    tmux_name=claim.name,
                    reuse_session_id=reuse_session_id,
                )
            elif claim.name != claim.base:
                logger.info(
                    "session_create_name_uniquified",
                    project=project_name,
                    base_tmux_name=claim.base,
                    uniquified_tmux_name=claim.name,
                    presence=claim.presence,
                )
            tmux_session_name = claim.name

        backend: Optional[SessionBackend] = None
        new_session: Optional[Session] = None
        try:
            backend = build_backend(
                settings,
                session_id=session_id,
                working_dir=work_path,
                on_output=self._make_output_handler(session_id),
                viewer_probe=self._make_viewer_probe(session_id),
                session_name=tmux_session_name,
            )

            self.hook_tokens.mint(session_id, tmux_name=tmux_session_name)
            registration = asyncio.Event()
            self._pending_agent_registration[session_id] = (tmux_session_name, registration)
            spawn_env = self.get_env_for_spawn(session_id)
            if auto_start_claude:  # active account
                spawn_env = await launch_env.new_pane_env(spawn_env, claude_account=claude_account)
            if extra_env:
                spawn_env = {**spawn_env, **dict(extra_env)}

            launched_family: Optional[str] = None
            recorded_agent_type: Optional[str] = resolved_agent_type
            launch_record_json: Optional[str] = None
            if auto_start_claude:
                from src.core.claude_rename import (
                    launch_name_args_for_agent_type,
                )

                name_args = launch_name_args_for_agent_type(
                    label=label,
                    agent_type=resolved_agent_type,
                    wrappers=_configured_wrappers(),
                )
                plan_sink: list = []
                command = settings.pane_launch_command(
                    resolved_agent_type, model=model, model_is_explicit=True, plan_sink=plan_sink,
                    extra_args=(agent_extra_args or []) + name_args,
                )
                if plan_sink:
                    prepared = await create_seam.prepare(plan_sink[0], account_id=claude_account)
                    spawn_env, launch_record_json = {**spawn_env, **prepared.staged}, prepared.record
                ran = launch_record(resolved_agent_type, _configured_wrappers())
                launched_family, recorded_agent_type = ran.family, ran.agent_type
                await backend.start(
                    command=command,
                    env=spawn_env,
                    initial_cols=initial_cols,
                    initial_rows=initial_rows,
                )
                if plan_sink:
                    await create_seam.scrub_staging(backend, prepared.staged)
            else:
                await backend.start(
                    env=spawn_env,
                    initial_cols=initial_cols,
                    initial_rows=initial_rows,
                )

            pid = getattr(backend, "pid", None)

            prior_pin = self._theme_store.resolve_project_theme(
                work_path, tmux_session_name
            )
            new_session = Session(
                id=session_id,
                pty_pid=pid,
                working_dir=str(work_path),
                status=SessionStatus.RUNNING,
                created_at=datetime.utcnow(),
                last_activity=datetime.utcnow(),
                agent_type=recorded_agent_type,
                model=model,
                pinned_theme=prior_pin,
                tmux_session=tmux_session_name,
            )

            self._registry.register(new_session, backend)
            registration.set()
            self._pending_agent_registration.pop(session_id, None)

            owned_name = getattr(backend, "tmux_session", None)
            if owned_name:
                self._owned.names.add(owned_name)

            self._save_session_metadata(new_session)

            if auto_start_claude and self._attention_watcher is not None:
                self._attention_watcher.begin_startup_quiet(session_id)
            create_persist_outcome = None
            if owned_name:
                persisted = self.persist_creation(
                    owned_name,
                    working_dir=str(work_path),
                    agent_type=recorded_agent_type,
                    agent_family=launched_family,
                    agent_launched=bool(auto_start_claude),
                    reuse_session_id=reuse_session_id,
                    label=label,
                    model=model,
                    launch_record=launch_record_json,
                    project_name=project_name,
                )
                create_persist_outcome = persisted.outcome
                new_session.tmux_created_epoch = persisted.epoch
                if persisted.epoch is not None:
                    self._instance_epochs[session_id] = persisted.epoch
                if not persisted.recorded:
                    logger.warning(
                        "session_created_not_attributed",
                        session_id=session_id,
                        tmux_name=owned_name,
                        outcome=persisted.outcome,
                        detail=persisted.detail,
                        note=(
                            "the session is LIVE; only its ownership row "
                            "is missing, so it will badge external until "
                            "it is recorded or adopted"
                        ),
                    )
            else:
                from src.core.session_create_persist import (
                    CREATE_NOT_TMUX_BACKED,
                )

                create_persist_outcome = CREATE_NOT_TMUX_BACKED

            logger.info(
                "session_created",
                session_id=session_id,
                pid=pid,
                backend=type(backend).__name__.replace("Backend", "").lower(),
                origin_persist=create_persist_outcome,
            )
            _record_stats_event("session_created", session_id)

            return new_session

        except PTYSessionError as e:
            logger.error("session_creation_failed", error=str(e))
            await self._cleanup_failed_create(session_id, backend)
            raise ValueError(f"Failed to create session: {e}") from e
        except RuntimeError as e:
            logger.error("session_creation_failed_runtime", error=str(e))
            await self._cleanup_failed_create(session_id, backend)
            raise
        except Exception as e:
            logger.error("session_creation_failed", error=str(e))
            await self._cleanup_failed_create(session_id, backend)
            raise ValueError(f"Failed to create session: {e}") from e
        finally:
            pending = self._pending_agent_registration.pop(session_id, None)
            if pending is not None:
                pending[1].set()

    async def _cleanup_failed_create(
        self,
        session_id: str,
        backend: Optional[SessionBackend],
    ) -> None:
        sess = self._registry.sessions.get(session_id)
        if sess is not None:
            sess.status = SessionStatus.ERROR
        if backend is not None:
            try:
                await backend.stop()
            except Exception as exc:
                logger.warning("backend_stop_failed_during_failure_cleanup", session_id=session_id, error=str(exc))
        self._wipe_session_state(session_id)

    async def detach_current_session(
        self, session_id: Optional[str] = None
    ) -> bool:
        sid = self._registry.resolve_session_id(session_id)
        backend = self._registry.backends.get(sid) if sid else None
        if not sid or backend is None:
            logger.info("detach_current_session_noop")
            return False

        logger.info("detaching_session", session_id=sid)

        try:
            reader_task = getattr(backend, "_reader_task", None)
            if reader_task is not None:
                try:
                    reader_task.cancel()
                    try:
                        await reader_task
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        logger.debug(
                            "reader_task_teardown_error_on_detach",
                            error=str(exc),
                        )
                except Exception as exc:
                    logger.debug(
                        "reader_task_cancel_error_on_detach", error=str(exc)
                    )
                try:
                    backend._reader_task = None
                except Exception:
                    pass

            try:
                if hasattr(backend, "_run_tmux"):
                    from src.core.tmux_backend import _safe_target
                    target_name = getattr(backend, "tmux_session", None)
                    if target_name:
                        await backend._run_tmux(
                            "pipe-pane",
                            "-t",
                            _safe_target(target_name),
                            check=False,
                        )
                try:
                    backend._running = False
                except Exception:
                    pass
            except Exception as exc:
                logger.warning(
                    "pipe_pane_stop_failed_on_detach", error=str(exc)
                )

            was_persisted = (self._registry.current_session() is not None and
                             self._registry.current_session().id == sid)
            self._wipe_session_state(sid)

            if was_persisted:
                metadata_path = settings.get_session_metadata_path()
                try:
                    if metadata_path.exists():
                        metadata_path.unlink()
                except OSError as exc:
                    logger.warning(
                        "session_metadata_unlink_failed_on_detach",
                        error=str(exc),
                    )
                if self._registry.current_session() is not None:
                    self._save_session_metadata()

            logger.info("session_detached", session_id=sid)
            return True

        except Exception as e:
            logger.error("session_detach_failed", error=str(e))
            raise

    async def destroy_session(self, session_id: Optional[str] = None) -> bool:
        sid = self._registry.resolve_session_id(session_id)
        if not sid:
            raise ValueError("No session to destroy")
        sess = self._registry.sessions.get(sid)
        backend = self._registry.backends.get(sid)
        if sess is None:
            raise ValueError("No session to destroy")

        logger.info("destroying_session", session_id=sid)

        try:
            owned_name = getattr(backend, "tmux_session", None) if backend else None
            remote = is_remote_backend(backend)
            if owned_name and not remote:
                self._owned.names.discard(owned_name)
                self._theme_store.discard_pin(owned_name)

            if backend is not None:
                await backend.stop()

            sess.status = SessionStatus.STOPPED

            working_dir = sess.working_dir
            if working_dir and not remote:
                verdict = sweep_verdict(working_dir)
                if verdict.outcome is SweepOutcome.SWEEP:
                    shutil.rmtree(verdict.bucket, ignore_errors=True)
                    logger.info(
                        "upload_dir_cleaned_on_destroy",
                        path=str(verdict.bucket),
                    )
                elif verdict.outcome is SweepOutcome.REFUSED:
                    logger.warning(
                        "upload_dir_cleanup_refused",
                        working_dir=str(working_dir),
                        reason=verdict.reason,
                    )

            was_persisted = (self._registry.current_session() is not None and
                             self._registry.current_session().id == sid)

            self._wipe_session_state(sid)

            if was_persisted:
                if self._registry.current_session() is not None:
                    self._save_session_metadata()
                else:
                    metadata_path = settings.get_session_metadata_path()
                    if metadata_path.exists():
                        metadata_path.unlink()

            logger.info("session_destroyed", session_id=sid)
            _record_stats_event("session_finished", sid)
            return True

        except Exception as e:
            logger.error("session_destruction_failed", error=str(e))
            raise

    def _is_live_tmux_name(self, candidate: str) -> bool:
        if not candidate:
            return False
        try:
            _socket, listing = self.list_attachable_sessions_with_socket()
            if not getattr(listing, "ok", False):
                return False
            return any(
                (row or {}).get("name") == candidate
                for row in (getattr(listing, "sessions", None) or [])
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("live_tmux_name_check_failed", error=str(exc))
            return False

    def set_session_label(self, session_id: str, label: str) -> bool:
        """Store the user-facing LABEL for one session. No tmux involved.

        Description: what the rename surface calls now. A label is a
          display string on the row; it is not the tmux session name and
          writing it touches no identity column, so a rename can no
          longer move ``tmux_name`` out from under the identity key and
          split one session into two rows.

          The tmux name and the creation epoch are read to KEY the write
          and are never modified. The epoch comes from a fresh listing
          because that is the only place it exists - the row is keyed on
          it, so a label write needs it just as much as a create does.

          NEVER RAISES for a data problem. A missing session, an
          unavailable datastore or a listing that could not answer all
          return False, which the route renders as a definite failure.
          An invalid label is the one exception, and it is raised before
          anything is read.
        Inputs: session_id (str) - the app's session id, not a tmux name.
          label (str) - the user's label; validated before any read.
        Output: bool - True only when a row now carries that label.
        Raises: InvalidLabel - the label cannot be stored.
        Example: mgr.set_session_label('abc123', 'Image Tool')
        """
        from src.core.session_label import set_label_for_instance, validate_label

        validate_label(label)

        sess = self._registry.sessions.get(session_id)
        tmux_name = getattr(sess, "tmux_session", None) if sess else None
        if not tmux_name:
            # running sessions
            tmux_name = self.hook_tokens.name_for(session_id)
        if not tmux_name and self._is_live_tmux_name(session_id):
            tmux_name = session_id
        if not tmux_name:
            logger.warning(
                "session_label_not_tmux_backed",
                session_id=session_id,
                note=(
                    "no tmux name for this session, so there is no "
                    "instance triple to key a label on"
                ),
            )
            return False

        probe_socket, listing = self.list_attachable_sessions_with_socket()
        socket = probe_socket or self._tmux_socket_name()
        if not listing.ok:
            logger.warning(
                "session_label_listing_unavailable",
                session_id=session_id,
                listing_reason=listing.reason,
                note=(
                    "the creation epoch could not be read, so the row "
                    "cannot be keyed. Nothing written - a label aimed at "
                    "a guessed instance is worse than no label"
                ),
            )
            return False

        from src.core.session_adopt_persist import find_live_instance

        live = find_live_instance(listing, tmux_name)
        if live is None:
            return False
        epoch = live.get("created_at_epoch")

        conn = self._writable_datastore_connection()
        if conn is None:
            return False
        try:
            from src.core.db import transaction

            with transaction(conn):
                stored = set_label_for_instance(
                    conn,
                    socket=socket,
                    name=tmux_name,
                    epoch=epoch,
                    label=label,
                )
            if stored:
                self._push_rename_to_claude(session_id, tmux_name, label)
            return stored
        except sqlite3.Error as exc:
            logger.warning(
                "session_label_write_failed",
                session_id=session_id,
                error=str(exc),
            )
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _push_rename_to_claude(
        self, session_id: str, tmux_name: str, label: str
    ) -> str:
        from src.core.claude_rename import (
            OOB_TIMEOUT_SECONDS,
            PUSH_SENT,
            decide_push,
            detect_claude_version,
            oob_rename_argv,
            spawn_oob_rename,
        )
        from src.core.session_transcript_presence import conversation_presence

        try:
            sess = self._registry.sessions.get(session_id)
            family = getattr(sess, "agent_family", None) if sess else None
            claude_uuid = self._claude_uuid_for_tmux_name(tmux_name)
            presence = conversation_presence(
                claude_uuid,
                working_dir=getattr(sess, "working_dir", None) if sess else None,
            )
            outcome, reason = decide_push(
                label=label,
                claude_uuid=claude_uuid,
                claude_version=detect_claude_version(),
                is_claude_session=(family in (None, "claude")),
                transcript_presence=presence.outcome,
            )
            if outcome != PUSH_SENT:
                logger.info(
                    "claude_rename_not_pushed",
                    session_id=session_id,
                    outcome=outcome,
                    reason=reason,
                    note="the CloudeCode label is stored either way",
                )
                return outcome

            from src.core.server_status import collect_claude_cli

            info = collect_claude_cli() or {}
            claude_path = info.get("path")
            if not claude_path:
                return "deferred"

            argv = oob_rename_argv(claude_path, claude_uuid, label)
            spawn_oob_rename(argv, session_id=session_id)
            logger.info(
                "claude_rename_pushed",
                session_id=session_id,
                reason=reason,
                timeout_s=OOB_TIMEOUT_SECONDS,
                note="spawned; the landed/rejected verdict follows separately",
            )
            return outcome
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "claude_rename_push_threw",
                session_id=session_id,
                error=str(exc),
            )
            return "deferred"

    def _claude_uuid_for_tmux_name(self, tmux_name: str) -> Optional[str]:
        conn = None
        try:
            conn = self._writable_datastore_connection()
            if conn is None:
                return None
            row = conn.execute(
                "SELECT claude_session_uuid FROM sessions "
                "WHERE tmux_name = ? AND tmux_created_epoch IS NOT NULL "
                "AND claude_session_uuid IS NOT NULL "
                "ORDER BY tmux_created_epoch DESC, id DESC LIMIT 1",
                (tmux_name,),
            ).fetchone()
            return row[0] if row else None
        except sqlite3.Error as exc:
            logger.debug("claude_uuid_lookup_failed", error=str(exc))
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    async def rename_session(
        self, session_id: str, new_name: str
    ) -> "SessionInfo":
        sess = self._registry.sessions.get(session_id)
        backend = self._registry.backends.get(session_id)
        if sess is None or backend is None:
            raise ValueError(f"Unknown session id: {session_id!r}")

        old_name = getattr(backend, "tmux_session", None)
        if not old_name:
            raise ValueError(
                f"Session {session_id!r} has no tmux name to rename"
            )

        if new_name == old_name:
            info = self._session_info_for(session_id)
            if info is None:
                raise ValueError(f"Session {session_id!r} not running")
            return info

        active = self.active_tmux_names()
        if new_name in active or new_name in self._owned.names:
            raise FileExistsError(
                f"Tmux session name {new_name!r} is already in use"
            )

        await backend.rename_session(new_name)

        if old_name in self._owned.names:
            self._owned.names.discard(old_name)
            self._owned.names.add(new_name)

        self._theme_store.rekey_pin(old_name, new_name)
        self.hook_tokens.rename_tmux(old_name, new_name)

        sess.tmux_session = new_name
        try:
            self._save_session_metadata(sess)
        except Exception as exc:
            logger.warning(
                "rename_session_metadata_persist_failed",
                session_id=session_id,
                old=old_name,
                new=new_name,
                error=str(exc),
            )

        logger.info(
            "session_renamed",
            session_id=session_id,
            old=old_name,
            new=new_name,
        )

        info = self._session_info_for(session_id)
        if info is None:
            raise ValueError(f"Session {session_id!r} not running")
        return info


    def _require_running(self, session_id: Optional[str]):
        sid = self._registry.resolve_session_id(session_id)
        if not sid:
            raise ValueError("No active session")
        sess = self._registry.sessions.get(sid)
        backend = self._registry.backends.get(sid)
        if sess is None or backend is None:
            raise ValueError("No active session")
        if sess.status != SessionStatus.RUNNING:
            raise ValueError(f"Session is not running (status: {sess.status})")
        return sid, sess, backend

    async def send_command(
        self, command: str, session_id: Optional[str] = None
    ) -> bool:
        sid, sess, backend = self._require_running(session_id)

        logger.info("sending_command", session_id=sid, length=len(command))

        try:
            await backend.write(command.encode("utf-8") + b"\n")
            sess.last_activity = datetime.utcnow()
            self._registry.count_command(sid)
            self._save_session_metadata(sess)
            return True
        except Exception as e:
            logger.error("send_command_failed", error=str(e))
            raise ValueError(f"Failed to send command: {e}") from e

    async def send_input(
        self, data: str, session_id: Optional[str] = None
    ) -> bool:
        sid, sess, backend = self._require_running(session_id)
        try:
            await backend.write(data.encode("utf-8"))
            sess.last_activity = datetime.utcnow()
            return True
        except Exception as e:
            logger.error("send_input_failed", error=str(e))
            raise ValueError(f"Failed to send input: {e}") from e

    def resize_terminal(
        self, cols: int, rows: int, session_id: Optional[str] = None
    ):
        sid = self._registry.resolve_session_id(session_id)
        backend = self._registry.backends.get(sid) if sid else None
        if backend is None:
            return
        try:
            backend.resize(cols, rows)
            logger.debug("terminal_resized", cols=cols, rows=rows, session_id=sid)
        except Exception as e:
            logger.error("terminal_resize_failed", error=str(e))

    def capture_scrollback(
        self, lines: int = 3000, session_id: Optional[str] = None
    ) -> bytes:
        sid = self._registry.resolve_session_id(session_id)
        backend = self._registry.backends.get(sid) if sid else None
        if backend is None:
            return b""
        try:
            return backend.capture_scrollback(lines=lines)
        except Exception as exc:
            logger.error("capture_scrollback_failed", error=str(exc))
            return b""


    def get_recent_logs(
        self, limit: int = 100, session_id: Optional[str] = None
    ) -> list[LogEntry]:
        sid = self._registry.resolve_session_id(session_id)
        if not sid:
            return []
        return self._registry.recent_logs(sid, limit)

    def add_log_entry(
        self, content: str, log_type: str = "stdout",
        session_id: Optional[str] = None,
    ) -> None:
        sid = self._registry.resolve_session_id(session_id)
        if not sid:
            return
        self._registry.append_log(sid, content=content, log_type=log_type)

    def publish_status_map(self, status_map: StatusMap) -> None:
        self._published_status_map = (time.monotonic(), status_map)

    def _status_map_for_listing(self) -> StatusMap:
        published = getattr(self, "_published_status_map", None)
        if published is not None:
            stamp, shared = published
            if getattr(shared, "complete", False) and time.monotonic() - stamp <= SHARED_STATUS_MAP_MAX_AGE_SECONDS:
                registered = {
                    getattr(b, "tmux_session", None) for b in list(self._registry.backends.values())
                    if not is_remote_backend(b)
                }
                registered.discard(None)
                if registered <= set(shared):
                    return shared
        return self._build_tmux_status_map()

    def _build_tmux_status_map(self) -> StatusMap:
        try:
            probe = build_backend(
                settings,
                session_id="__status_probe__",
                working_dir=Path.home(),
                on_output=None,
            )
            if not hasattr(probe, "list_pane_status_all"):
                return StatusMap()
            listing = coerce_listing(probe.list_pane_status_all())
            if not listing.ok:
                logger.warning(
                    "tmux_status_map_unavailable",
                    reason=listing.reason,
                    detail=listing.detail,
                    note="every session status falls back to unknown",
                )
                return StatusMap()
            return status_map_from_listing(
                listing, socket=getattr(probe, "socket_name", None)
            )
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            logger.warning("tmux_status_map_build_failed", error=str(exc))
            return StatusMap()

    def _startup_gate_for(
        self,
        *,
        session_id: str,
        backend,
        tmux_name: Optional[str],
        row: Optional[dict],
        liveness: str,
    ) -> str:
        """Resolve this session's startup-prompt gate, and toast it once.

        Description: the ONE bridge between the listing pass and
          ``src.core.session_startup_gate``. Everything that needs tmux
          or mutable state happens here; the ladder itself stays pure and
          is tested without a tmux server.

          The pane tail - the only expensive input - is captured ONLY
          when ``should_capture_tail`` says the cheap signals already
          point at a stuck session (alive, past the grace window, no hook
          for this instance). On a working box that set is empty, so a
          steady-state listing poll pays nothing at all for this feature.
        """
        if not tmux_name:
            return GATE_UNKNOWN

        inputs = startup_tail_prefetch.gate_inputs(
            self._startup_gate_ledger, tmux_name, row, liveness
        )

        tail: Optional[str] = None
        took_tail = False
        if startup_tail_prefetch.wants_tail(self._startup_gate_ledger, tmux_name, inputs):
            socket_name = getattr(backend, "socket_name", None)
            if socket_name:
                tail = startup_tail_prefetch.take_tail(
                    self._startup_gate_ledger, socket_name, tmux_name, capture_pane_tail)
                took_tail = True

        if took_tail:
            self._startup_gate_ledger.record_tail_read(
                tmux_name, matched=detect_startup_prompt(tail)
            )

        gate = resolve_startup_gate(
            pane_alive=inputs.pane_alive,
            first_hook_at=inputs.first_hook_at,
            instance_age_seconds=inputs.age_seconds,
            tail=tail,
            remembered_match=self._startup_gate_ledger.last_tail_match(
                tmux_name
            ),
        )
        return gate

    def _session_info_for(
        self,
        session_id: str,
        status_map: Optional[dict] = None,
        instance_index: Optional[Any] = None,
        prefetch: Optional[ListingPrefetch] = None,
        model_facts: Optional[Mapping[str, ModelListingFacts]] = None,
        remote: Optional[Any] = None,
        owned_db: Any = DB_INSTANCES_UNSET,
    ) -> Optional[SessionInfo]:
        """Build SessionInfo for a specific live session, or None.

        ``owned_db`` is the pass's ONE read of the owned instances in the
        datastore (``None`` = it could not answer), taken on the loop right
        before the per-row loop so an adoption is as fresh as ever; omitted,
        the ownership check reads the datastore itself, as single-session
        callers always did.

        ``status_map`` (optional) lets a caller iterating many sessions
        (``list_session_infos``) build the bulk tmux status query ONCE and
        pass it in, instead of every session triggering its own subprocess
        call. When omitted, a fresh single-use map is built here so
        single-session callers (``get_session_info``) still get a real
        status without the caller having to know about the map.

        ``instance_index`` is the SAME IDEA FOR THE DATASTORE, and it is
        the second per-row cost this pass used to pay. The status seed
        ladder reads four columns off this session's row, keyed on the
        instance triple, through
        ``session_status_seed_read.read_instance_row`` - which opened its
        OWN SQLite connection, per session. A listing caller reads every
        row it needs in ONE query and passes the index here. When omitted
        (a single-session caller) the seed does exactly what it always
        did, so this is a saving on the pass and never a change of
        answer.

        THE FOURTH, ``is_owned_tmux_name``, IS STILL READ HERE, LIVE, PER
        ROW. It is the only one of the four an ADOPTION can move, and an
        adoption can now land while the gather thread runs, so gathering
        it would drop ``created_by_cloude`` off a freshly adopted row for
        one poll cycle. See that method's docstring.

        ABSENT IS NOT AN ANSWER. A name the prefetch was not built over -
        including every name when no prefetch is passed at all - falls
        through to the live read it always made, so ``get_session_info``
        and every other single-session caller is byte-identical.

        The returned ``SessionInfo.session.pty_pid`` is resolved LIVE off
        that same status map (see the ``live_pid`` block below) rather than
        trusting whatever was captured on ``Session`` at creation/adopt
        time - see fix/adopted-session-pid.
        """
        sess = self._registry.sessions.get(session_id)
        backend = self._registry.backends.get(session_id)
        if sess is None or backend is None:
            return None
        if is_remote_backend(backend):
            return remote_sessions.remote_session_info(self, session_id, remote)
        if sess.status != SessionStatus.RUNNING:
            return None
        uptime = int((datetime.utcnow() - sess.created_at).total_seconds())
        stats = SessionStats(
            total_commands=self._registry.command_count(session_id),
            uptime_seconds=uptime,
            log_lines=self._registry.log_line_count(session_id),
            local_servers=0,
        )
        tmux_session_name = getattr(backend, "tmux_session", None)
        backend_name = backend.__class__.__name__.replace("Backend", "").lower()

        if status_map is None:
            status_map = self._build_tmux_status_map()
        row = status_map.get(tmux_session_name) if tmux_session_name else None
        raw_tmux_status = row["status"] if row else STATUS_UNKNOWN

        listing_says_present = listing_proves_alive(
            status_map,
            tmux_session_name,
            backend_socket=getattr(backend, "socket_name", None),
        )
        liveness = resolve_listing_liveness(
            exists=(listing_says_present or backend.is_alive()),
            pane_status=raw_tmux_status if tmux_session_name else None,
        )
        if liveness == LIVENESS_GONE:
            pane_measured_dead = (
                listing_says_present and raw_tmux_status == STATUS_DEAD
            )
            session_permission_verify_apply.verify_open_permission(
                self,
                session_id=session_id,
                backend=backend,
                tmux_name=tmux_session_name,
                pane_alive=False if pane_measured_dead else None,
            )
            return None
        if liveness == LIVENESS_UNKNOWN:
            raw_tmux_status = STATUS_UNKNOWN
        # something else
        row_identity = (
            prefetch.identity_for(tmux_session_name)
            if prefetch is not None and prefetch.has(tmux_session_name)
            else self._identity_for_live_name(tmux_session_name)
        )
        evidence = choose_agent_evidence(
            memory_agent_type=sess.agent_type,
            memory_from_fingerprint=sess.agent_type_via_fingerprint,
            row_agent_type=(
                row_identity.get("agent_type") if row_identity else None
            ),
            row_family_source=(
                row_identity.get("agent_family_source") if row_identity else None
            ),
        )
        effective_agent_type = evidence.agent_type
        from_fingerprint = evidence.from_fingerprint
        from_process = evidence.from_process
        wrappers = _configured_wrappers()
        display_family, display_family_source = resolve_family_for_display(
            effective_agent_type,
            wrappers,
            from_fingerprint=from_fingerprint,
            from_process=from_process,
        )
        # something else
        recorded = recorded_launch_family(
            row_agent_family=(
                row_identity.get("agent_family") if row_identity else None
            ),
            row_family_source=(
                row_identity.get("agent_family_source") if row_identity else None
            ),
            row_agent_type=(
                row_identity.get("agent_type") if row_identity else None
            ),
            effective_agent_type=effective_agent_type,
        )
        if recorded is not None:
            display_family, display_family_source = recorded
        # nothing at all
        wrapper_display = resolve_wrapper_for_display(
            effective_agent_type,
            wrappers,
            from_fingerprint=from_fingerprint,
        )

        # that name is already taken
        running_model = running_model_effort = None
        running_model_tier: Optional[int] = None
        running_context_used_pct: Optional[float] = None
        resolved_family_name = display_family.name if display_family else None
        if model_facts is not None and tmux_session_name in model_facts:
            row_model_facts = model_facts[tmux_session_name]
            if row_model_facts.family == resolved_family_name:
                running_model = row_model_facts.model
                running_model_effort = row_model_facts.model_effort
                running_model_tier = row_model_facts.model_tier
                running_context_used_pct = row_model_facts.context_used_pct

        pane_epoch = unread_identity.remember(
            self._unread_epochs,
            tmux_session_name,
            unread_identity.epoch_of_row(row),
        ) or unread_identity.resolve_epoch(
            self._unread_epochs, tmux_session_name
        )
        unread = self._is_unread(tmux_session_name, pane_epoch, unread_follow_up.remember_row(
            self._unread_rows, tmux_session_name, pane_epoch,
            row_identity["id"] if row_identity else None))
        watcher = self._attention_watcher
        observation = (
            watcher.observation_for(session_id, now=datetime.now(timezone.utc))
            if watcher is not None else None
        )
        if observation is not None:
            verdict = observation.verdict
            activity_status = to_display(
                verdict, unread=unread, tmux_status=raw_tmux_status,
            )
            status_source = status_source_for(verdict)
            activity_hint = verdict.activity_hint or activity_hint_for(
                observation.evidence.registry
            )
        else:
            activity_status, status_source, activity_hint = (
                listing_attention.resolve_row_status_live(
                    tmux_name=tmux_session_name,
                    epoch=row.get("created_at_epoch") if row else None,
                    index=instance_index,
                    family=display_family.name if display_family else None,
                    liveness=liveness,
                    unread=unread,
                    tmux_status=raw_tmux_status,
                    working_dir=sess.working_dir,
                    now=datetime.now(timezone.utc),
                    restarted_at=watcher.process_floor_for(session_id) if watcher is not None else None,
                )
            )

        activity_status = derive_read_state(activity_status, unread=unread)

        startup_gate = gate_with_screen(self._startup_gate_for(
            session_id=session_id, backend=backend, tmux_name=tmux_session_name,
            row=row, liveness=liveness,
        ), observation)

        # could not
        live_pid = row.get("pid") if row else None
        if live_pid is None:
            live_pid = getattr(backend, "pid", None)
        if live_pid is None:
            live_pid = sess.pty_pid
        sess_out = sess.model_copy(
            update={"pty_pid": live_pid, "tmux_created_epoch": pane_epoch}
        )

        return SessionInfo(
            session=sess_out,
            recent_logs=self.get_recent_logs(session_id=session_id),
            local_servers=[],
            stats=stats,
            session_backend=backend_name,
            tmux_session=tmux_session_name,
            label=(
                prefetch.label_for(tmux_session_name)
                if prefetch is not None and prefetch.has(tmux_session_name)
                else self._label_for_tmux_name(tmux_session_name)
            ),
            session_row_id=row_identity["id"] if row_identity else None,
            parent_session_id=(
                row_identity["parent_session_id"] if row_identity else None
            ),
            claude_session_uuid=(
                row_identity.get("claude_session_uuid") if row_identity else None
            ),
            project_id=(
                row_identity.get("project_id") if row_identity else None
            ),
            project_name=(
                row_identity.get("project_name") if row_identity else None
            ),
            agent_type=effective_agent_type,
            agent_family=display_family.name if display_family else None,
            agent_family_source=display_family_source,
            agent_wrapper_label=wrapper_display.label,
            launched_with=launched_with_for_row(row_identity, settings),
            running_model=running_model,
            running_model_effort=running_model_effort,
            running_model_tier=running_model_tier,
            running_context_used_pct=running_context_used_pct,
            pinned_theme=sess.pinned_theme,
            activity_status=activity_status,
            status_source=status_source,
            activity_hint=activity_hint,
            unread=unread,
            startup_gate=startup_gate,
            # could not be read
            notifications_muted=self.notification_policy_for(
                session_id
            ).muted,
            created_by_cloude=bool(
                tmux_session_name
                and self._owned.is_owned_name(
                    tmux_session_name,
                    **({} if owned_db is DB_INSTANCES_UNSET else {"db_instances": owned_db}),
                )
            ),
        )

    async def get_session_info(
        self, session_id: Optional[str] = None
    ) -> Optional[SessionInfo]:
        sid = self._registry.resolve_session_id(session_id)
        if not sid:
            return None
        status_map = await asyncio.to_thread(self._status_map_for_listing)
        await startup_tail_prefetch.prefetch(self, status_map, [sid], capture_pane_tail)
        return self._session_info_for(sid, status_map=status_map)

    async def list_session_infos(self) -> list[SessionInfo]:
        snapshot = self._listing_snapshot()
        registrations = session_ghost_reap.snapshot_registrations(
            self._registry.backends
        )
        gathered = await asyncio.to_thread(
            listing_gather.gather_listing_inputs,
            self._listing_readers(),
            snapshot,
        )
        listing_gather.log_gather(gathered, snapshot.decorated_names)
        await session_ghost_reap.reap_after_listing(
            self, registrations, gathered.status_map
        )
        await remote_sessions.reap_remote(self, snapshot.remote_targets, gathered.remote)
        out: list[SessionInfo] = []
        owned_db = await asyncio.to_thread(self._owned.instances_from_db)
        ids = self._registry.listable_ids()
        await startup_tail_prefetch.prefetch(self, gathered.status_map, ids, capture_pane_tail)
        for sid in ids:
            info = self._session_info_for(
                sid,
                owned_db=owned_db,
                status_map=gathered.status_map,
                instance_index=gathered.instance_index,
                prefetch=gathered.prefetch,
                model_facts=gathered.model_facts, remote=gathered.remote,
            )
            if info is not None:
                out.append(info)
        self._agent_resweep.maybe_schedule(self, out)
        return out

    def _listing_snapshot(self) -> "listing_gather.ListingSnapshot":
        return listing_gather.ListingSnapshot(
            socket=self._tmux_socket_name(),
            seed_candidate_names=tuple(self._seed_candidate_tmux_names()),
            decorated_names=tuple(
                name for _sid, name in self._listed_tmux_names_by_session()
            ),
            remote_targets=remote_sessions.snapshot_targets(self),
        )

    def _listing_readers(self) -> "listing_gather.ListingReaders":
        return listing_gather.ListingReaders(
            build_status_map=self._status_map_for_listing,
            build_instance_index=self._instance_index_for_listing,
            label_for_name=self._label_for_tmux_name,
            identity_for_live_name=self._identity_for_live_name,
            label_identity_for_names=self._label_identity_for_names,
            gather_remote=remote_sessions.gather_for(self),
            shared_connection=lambda: lend_name_read_connection(self),
        )

    def _seed_candidate_tmux_names(self) -> list[str]:
        return [name for _sid, name in self._listed_tmux_names_by_session()]

    def _listed_tmux_names_by_session(self) -> list[tuple]:
        """Every tmux name this pass may need a stored row for.

        Description: read off the BACKENDS, which is where
          ``_session_info_for`` reads the name it then looks the row up
          by (``getattr(backend, "tmux_session")``). Reading it from
          anywhere else would be a second derivation of one key, and two
          derivations are two keys the moment they disagree - here that
          would show as a session silently missing from the index and
          falling back to its own connection, which is invisible except
          in a subprocess count.

          IT IS TAKEN FROM THE SESSIONS THE MANAGER HOLDS, NOT FROM THE
          TMUX LISTING. The index answers None for a name it was not
          built over, and for the seed a None reads as "this instance
          could not be identified" - so building it over the tmux
          listing would refuse the seed for any registered session the
          listing did not name, which is a different set.
        Inputs: none.
        Output: list[tuple[str, str]] - (session_id, tmux_name) pairs,
          deduplicated by NAME, order preserved, no falsy entries.
        Example: mgr._listed_tmux_names_by_session() -> [('ses_1', 'cloude_a')]
        """
        hook_names = self.hook_tokens.tmux_names
        pairs: list[tuple] = []
        seen: set = set()
        for session_id in list(self._registry.sessions.keys()):
            backend = self._registry.backends.get(session_id)
            name = getattr(backend, "tmux_session", None) or hook_names.get(
                session_id
            )
            if name and name not in seen:
                seen.add(name)
                pairs.append((session_id, name))
        return pairs

    def has_active_session(self) -> bool:
        for sid, backend in list(self._registry.backends.items()):
            sess = self._registry.sessions.get(sid)
            if (
                sess is not None
                and sess.status == SessionStatus.RUNNING
                and backend.is_alive()
            ):
                return True
        return False

    def health_summary(self) -> Optional[tuple[str, int]]:
        sess = self._registry.current_session()
        if sess is None or sess.status != SessionStatus.RUNNING:
            return None
        uptime = int((datetime.utcnow() - sess.created_at).total_seconds())
        return os.path.basename(sess.working_dir), uptime

    def is_session_live(self, session_id: str) -> bool:
        sess = self._registry.sessions.get(session_id)
        backend = self._registry.backends.get(session_id)
        return (
            sess is not None
            and sess.status == SessionStatus.RUNNING
            and backend is not None
            and backend.is_alive()
        )


    def _is_remote_sid(self, session_id: str) -> bool:
        return is_remote_backend(self._registry.backends.get(session_id))

    def active_tmux_names(self) -> set[str]:
        names: set[str] = set()
        for backend in self._registry.backends.values():
            n = getattr(backend, "tmux_session", None)
            if n and not is_remote_backend(backend):
                names.add(n)
        return names

    # could not

    def _datastore_connection(self):
        try:
            from src.core.db import connect, db_path_for

            path = db_path_for(settings.get_state_dir())
            if not Path(path).exists():
                return None
            return connect(path, create=False)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ownership_datastore_unavailable", error=str(exc))
            return None

    def _writable_datastore_connection(self):
        """Open the datastore for WRITING, or return None.

        Description: the sibling of :meth:`_datastore_connection`, which
          is deliberately ``create=False`` because it serves the RENDER
          path and must never bring a database into existence as a side
          effect of drawing a badge. This one is used by the adopt path,
          which is an explicit user action on an app that has already
          booted, so the file is expected to be there; it still declines
          to create one, because an adoption that silently births a fresh
          empty datastore would lose the install's history rather than
          record a claim into it.
        Inputs: none (reads ``settings.get_state_dir()``).
        Output: sqlite3.Connection | None - None when the datastore
          cannot be opened at all, which the caller must report as
          COULD NOT EVALUATE and never as a failed adoption.

          NO ARCHIVE ATTACHED, for the reason on
          :meth:`_datastore_connection` and with more force: this one
          WRITES, so every call takes a ``BEGIN IMMEDIATE`` and would
          take the archive's write lock with it. Its callers are
          main-only by the same audit.
        """
        try:
            from src.core.db import connect, db_path_for

            path = db_path_for(settings.get_state_dir())
            if not Path(path).exists():
                return None
            return connect(path, create=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("adopt_datastore_unavailable", error=str(exc))
            return None

    def record_claude_lifecycle_event(
        self,
        session_id: str,
        event_kind: str,
        payload: dict,
        *,
        uuid_source: str = SESSION_CLAUDE_UUID_SOURCE_HOOK,
        tmux_name: Optional[str] = None,
    ):
        from src.core.session_lineage import (
            LINEAGE_CONTINUED,
            LINEAGE_UNRESOLVED,
            LineageResult,
            record_claude_session,
        )

        if event_kind != "SessionStart":
            if event_kind == "SessionEnd":
                ended = payload.get("session_id") if isinstance(payload, dict) else None
                if isinstance(ended, str) and ended:
                    self._last_session_end_uuid[session_id] = ended
            return LineageResult(
                outcome=LINEAGE_CONTINUED,
                detail=f"{event_kind} carries no lineage transition",
            )

        claude_uuid = payload.get("session_id") if isinstance(payload, dict) else None
        empty_payload = not isinstance(claude_uuid, str) or not claude_uuid
        if empty_payload:
            recovered = self._recover_lineage_without_payload(session_id)
            if recovered is not None:
                return recovered
            return LineageResult(
                outcome=LINEAGE_UNRESOLVED,
                detail=(
                    "the SessionStart payload carried no session_id, and the "
                    "correlation ladder could not identify the conversation "
                    "from the pane's own evidence either"
                ),
            )

        if not tmux_name:
            session = self._registry.get_session(session_id)
            tmux_name = (
                getattr(session, "tmux_session", None) if session else None
            )
        if not tmux_name:
            # CLOUDECODE_SESSION_ID
            tmux_name = self.hook_tokens.name_for(session_id)
            if tmux_name:
                logger.info(
                    "lineage_resolved_from_persisted_name",
                    session_id=session_id,
                    note="session id predates a restart; resolved by tmux name",
                )
        if not tmux_name:
            return LineageResult(
                outcome=LINEAGE_UNRESOLVED,
                detail=(
                    "no live session carries this cloudecode session id, and "
                    "no persisted tmux name is recorded for it"
                ),
            )

        conn = self._writable_datastore_connection()
        if conn is None:
            return LineageResult(
                outcome=LINEAGE_UNRESOLVED,
                detail="the datastore could not be opened to record lineage",
            )
        try:
            pane_left_previous = (
                self._last_session_end_uuid.pop(session_id, None) is not None
            )

            from src.core.db import transaction

            from src.core.session_adopt_persist import find_live_instance

            probe_socket, listing = self.list_attachable_sessions_with_socket()
            socket = probe_socket or self._tmux_socket_name()

            # could not
            if not getattr(listing, "ok", False):
                return LineageResult(
                    outcome=LINEAGE_UNRESOLVED,
                    detail=(
                        "the tmux listing could not run, so the instance "
                        f"could not be identified: {getattr(listing, 'reason', None)}"
                    ),
                )
            live = find_live_instance(listing, tmux_name)
            if live is None:
                return LineageResult(
                    outcome=LINEAGE_UNRESOLVED,
                    detail=(
                        f"tmux session {tmux_name!r} is not in a listing that ran"
                    ),
                )
            try:
                epoch = int(live.get("created_at_epoch"))
            except (TypeError, ValueError):
                epoch = None

            with transaction(conn):
                return record_claude_session(
                    conn,
                    socket=socket,
                    name=tmux_name,
                    epoch=epoch,
                    claude_uuid=claude_uuid,
                    source=payload.get("source"),
                    title=payload.get("session_title"),
                    pane_left_previous=pane_left_previous,
                    uuid_source=uuid_source,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "claude_lineage_record_failed",
                session=session_id,
                event_kind=event_kind,
                error=str(exc),
            )
            return LineageResult(
                outcome=LINEAGE_UNRESOLVED,
                detail=f"could not record lineage: {exc}",
            )
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def persist_adoption(self, name: str):
        from src.core.session_adopt_persist import (
            PERSIST_LISTING_UNAVAILABLE,
            AdoptPersistResult,
            persist_adoption,
        )

        conn = self._writable_datastore_connection()
        if conn is None:
            return AdoptPersistResult(
                outcome=PERSIST_LISTING_UNAVAILABLE,
                detail="the datastore could not be opened to record the claim",
            )
        try:
            from src.core.db import transaction
            from src.core.tmux_session_cwd import make_working_dir_probe
            from src.core.tmux_session_pane_pid import make_pane_pid_probe
            from src.core.session_adopt_dead_gate import make_pane_dead_probe

            probe_socket, listing = self.list_attachable_sessions_with_socket()
            socket = probe_socket or self._tmux_socket_name()
            with transaction(conn):
                result = persist_adoption(
                    conn,
                    socket=socket,
                    name=name,
                    listing=listing,
                    working_dir_probe=make_working_dir_probe(socket),
                    pane_pid_probe=make_pane_pid_probe(socket),
                    pane_dead_probe=make_pane_dead_probe(socket),
                )
            from src.core.session_agent_infer_sweep import sweep_live_sessions

            sweep_live_sessions(self)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "adopt_persist_failed", session=name, error=str(exc)
            )
            return AdoptPersistResult(
                outcome=PERSIST_LISTING_UNAVAILABLE,
                detail=f"could not record the claim: {exc}",
            )
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def _recover_lineage_without_payload(self, session_id: str):
        """Second chance for a SessionStart whose payload arrived empty.

        Description: resolves the pane behind ``session_id`` and runs the
          SAME correlation ladder the adopt path runs
          (:mod:`src.core.session_lineage_recovery`), so the create path
          stops depending on a single hook delivery that cannot be
          retried. Returns None whenever it could not even attempt the
          recovery, so the caller reports the original, honest failure
          rather than a recovery that never ran.

          BEST EFFORT AND SILENT ON FAILURE. This runs inside a live
          session's hook request; nothing here may raise, and nothing
          here may turn a telemetry gap into a 500.
        Inputs: session_id (str) - the cloudecode session id from the
          hook header.
        Output: LineageResult | None - a bound result, or None to fall
          through to the caller's UNRESOLVED.
        Example: mgr._recover_lineage_without_payload('ses_a')
        """
        from src.core.session_lineage import LINEAGE_BOUND, LineageResult
        from src.core.session_lineage_recovery import (
            RECOVERY_BOUND,
            recover_claude_uuid,
        )

        session = self._registry.get_session(session_id)
        tmux_name = getattr(session, "tmux_session", None) if session else None
        if not tmux_name:
            tmux_name = self.hook_tokens.name_for(session_id)
        if not tmux_name:
            return None

        conn = self._writable_datastore_connection()
        if conn is None:
            return None
        try:
            from src.core.db import transaction
            from src.core.session_adopt_persist import find_live_instance
            from src.core.tmux_session_pane_pid import make_pane_pid_probe

            probe_socket, listing = self.list_attachable_sessions_with_socket()
            socket = probe_socket or self._tmux_socket_name()
            if not getattr(listing, "ok", False):
                return None
            live = find_live_instance(listing, tmux_name)
            if live is None:
                return None
            try:
                epoch = int(live.get("created_at_epoch"))
            except (TypeError, ValueError):
                epoch = None

            working_dir = getattr(session, "working_dir", None) if session else None
            if not working_dir:
                working_dir = live.get("working_dir")

            pane_pid = None
            try:
                pane_pid = make_pane_pid_probe(socket)(tmux_name)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "lineage_recovery_pane_pid_failed",
                    session=tmux_name,
                    error=str(exc),
                )

            with transaction(conn):
                outcome, uuid = recover_claude_uuid(
                    conn,
                    socket=socket,
                    tmux_name=tmux_name,
                    tmux_created_epoch=epoch,
                    working_dir=working_dir,
                    pane_pid=pane_pid,
                )
            if outcome == RECOVERY_BOUND:
                return LineageResult(
                    outcome=LINEAGE_BOUND,
                    detail=(
                        f"SessionStart delivered no session_id; {uuid} "
                        "recovered from the pane's own evidence"
                    ),
                )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "lineage_recovery_failed", session=session_id, error=str(exc)
            )
            return None
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def _persist_fingerprint_family(
        self, *, session_uuid: str, agent_family: str
    ) -> None:
        conn = None
        try:
            from src.core.db import transaction
            from src.core.session_agent_provenance import (
                persist_fingerprint_family,
            )

            conn = self._writable_datastore_connection()
            if conn is None:
                return
            with transaction(conn):
                persist_fingerprint_family(
                    conn,
                    session_uuid=session_uuid,
                    agent_family=agent_family,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "adopt_fingerprint_family_persist_threw",
                session_uuid=session_uuid,
                agent_family=agent_family,
                error=str(exc),
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    def persist_creation(
        self,
        name: str,
        working_dir: Optional[str] = None,
        agent_type: Optional[str] = None,
        agent_family: Optional[str] = None,
        agent_launched: Optional[bool] = None,
        reuse_session_id: Optional[int] = None,
        label: Optional[str] = None,
        model: Optional[str] = None,
        launch_record: Optional[str] = None,
        project_name: Optional[str] = None,
    ):
        from src.core.session_create_persist import (
            CREATE_NO_DATASTORE,
            CreatePersistResult,
            persist_creation,
        )

        conn = self._writable_datastore_connection()
        if conn is None:
            logger.warning(
                "create_persist_no_datastore",
                tmux_name=name,
                note=(
                    "the session is live but there is no datastore to "
                    "record it in, so its ownership rests on the "
                    "degraded in-memory tier until one exists"
                ),
            )
            return CreatePersistResult(
                outcome=CREATE_NO_DATASTORE,
                detail="the datastore could not be opened to record the session",
            )
        try:
            from src.core.db import transaction
            from src.core.tmux_session_cwd import make_working_dir_probe

            probe_socket, listing = self.list_attachable_sessions_with_socket()
            socket = probe_socket or self._tmux_socket_name()
            with transaction(conn):
                return persist_creation(
                    conn,
                    socket=socket,
                    name=name,
                    listing=listing,
                    agent_type=agent_type,
                    agent_family=agent_family,
                    agent_launched=agent_launched,
                    working_dir=working_dir,
                    working_dir_probe=make_working_dir_probe(socket),
                    reuse_session_id=reuse_session_id,
                    label=label,
                    model=model,
                    launch_record=launch_record,
                    project_name=project_name,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "create_persist_failed",
                session=name,
                error=str(exc),
                note=(
                    "the session itself is unaffected; only its ownership "
                    "record failed to write"
                ),
            )
            return CreatePersistResult(
                outcome=CREATE_NO_DATASTORE,
                detail=f"could not record the new session: {exc}",
            )
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def _tmux_socket_name(self) -> str:
        from src.core.product_identity import TMUX_SOCKET_NAME
        from src.core.tmux_socket_resolution import configured_tmux_socket_name

        configured = configured_tmux_socket_name(settings) or TMUX_SOCKET_NAME
        return self._probe_health.socket_name(configured=configured)

    def tmux_socket_name(self) -> str:
        return self._tmux_socket_name()

    def _fingerprint_agent_type_for_listing(
        self, *, socket: str, name: str, epoch: Optional[int]
    ) -> Optional[str]:
        """Detect which agent CLI a listed tmux instance is running.

        Description: the LISTING-TIME counterpart to the fingerprint scan
          ``adopt_external_session`` already runs. That path captures
          scrollback through a fully attached backend (pipe-pane, FIFO,
          resize) because it needs the bytes for first-paint replay too;
          this one only needs to know which agent is running, so it uses
          a bare ``TmuxBackend.for_external`` (no attach, no pipe-pane -
          one ``tmux capture-pane`` subprocess call and nothing else) and
          throws the bytes away after scanning them.

          Cached per instance triple in ``self._listing_fingerprint_cache``
          so a listing poll after the first never re-probes tmux for a
          session it has already seen - see that field's docstring for
          why this is safe and what it trades away. A ``None`` epoch
          cannot be cached (no stable key), so it is fingerprinted fresh
          every call - this only happens for a row tmux itself could not
          date, which S5's listing parser already treats as a refused
          row in the common path.
        Inputs: socket (str) - tmux socket the row was listed on.
          name (str) - tmux session name. epoch (int | None) -
          ``#{session_created}``, the instance discriminator.
        Output: str | None - a value from
          ``agent_fingerprint.AGENT_FINGERPRINTS`` (e.g. ``"codex"``), or
          None when nothing matched or the probe failed. None is cached
          exactly like a hit: "fingerprinted, found nothing" is itself an
          answer worth not re-asking for.
        Example:
          mgr._fingerprint_agent_type_for_listing(
              socket='cloude', name='cloude_a', epoch=1723999999)
        """
        if epoch is None:
            return self._detect_agent_type_from_pane(socket=socket, name=name)

        key = (socket, name, int(epoch))
        if key in self._listing_fingerprint_cache:
            return self._listing_fingerprint_cache[key]

        detected = self._detect_agent_type_from_pane(socket=socket, name=name)
        self._listing_fingerprint_cache[key] = detected
        return detected

    def _detect_agent_type_from_pane(
        self, *, socket: str, name: str
    ) -> Optional[str]:
        from src.core.agent_fingerprint import detect_agent_type

        scrollback_text = capture_pane_tail(
            socket=socket, name=name, lines=2000
        )
        if scrollback_text is None:
            return None
        return detect_agent_type(scrollback_text)

    def _stored_launch_for_listing(self, *, socket, name, epoch):
        from src.core.session_agent_provenance import (
            NOT_KNOWN,
            stored_launch_for,
        )

        conn = None
        try:
            conn = self._writable_datastore_connection()
        except Exception:
            conn = None
        if conn is None:
            return NOT_KNOWN
        try:
            return stored_launch_for(
                conn, socket=socket, name=name, epoch=epoch
            )
        except Exception as exc:
            logger.debug("stored_launch_lookup_threw", error=str(exc))
            return NOT_KNOWN
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _label_for_tmux_name(self, tmux_name):
        from src.core.session_label import label_for_name

        if not tmux_name:
            return None
        conn, owned = None, False
        try:
            conn, owned = self._name_read_connection()
            if conn is None:
                return None
            return label_for_name(
                conn, socket=self._tmux_socket_name(), name=tmux_name
            )
        except Exception as exc:
            logger.debug("session_label_read_threw", error=str(exc))
            return None
        finally:
            if conn is not None and owned:
                try:
                    conn.close()
                except Exception:
                    pass

    def _label_identity_for_names(self, names):
        with lend_name_read_connection(self):
            return {
                name: (self._label_for_tmux_name(name), self._identity_for_live_name(name))
                for name in names
            }

    def _name_read_connection(self):
        lent = getattr(self._borrowed, "conn", None)
        return (lent, False) if lent is not None else (lend_for_state_dir(lambda: settings.get_state_dir()), False)

    def _identity_for_live_name(self, tmux_name):
        from src.core.session_store import identity_for_live_name

        if not tmux_name:
            return None
        conn, owned = None, False
        try:
            conn, owned = self._name_read_connection()
            if conn is None:
                return None
            return identity_for_live_name(
                conn, socket=self._tmux_socket_name(), name=tmux_name
            )
        except Exception as exc:
            logger.debug("session_identity_live_read_threw", error=str(exc))
            return None
        finally:
            if conn is not None and owned:
                try:
                    conn.close()
                except Exception:
                    pass

    def _instance_index_for_listing(self, *, socket, names):
        """Read every listed instance's stored row on ONE connection.

        Description: the bulk replacement for three per-row lookups that
          each opened their own SQLite connection. Opens one connection,
          issues one query, closes it, and hands back an index the
          listing loop answers from - see
          ``src/core/session_instance_index.py`` for the measurement and
          for why the two differing selection rules are both preserved.

          NEVER RAISES, and an unopenable datastore yields an EMPTY
          index. That is not a silent degradation: an empty index answers
          ``None`` for the label and identity and ``NOT_KNOWN`` for the
          launch, which is exactly what each per-row reader returned when
          it could not open the database either.
        Inputs: socket (str) - the tmux socket the listing came from.
          names (iterable[str | None]) - the listed tmux names; falsy
          entries are ignored.
        Output: InstanceIndex - possibly empty, never None.
        Example: self._instance_index_for_listing(
            socket='cloude', names=['cloude_a'])
        """
        from src.core.session_instance_index import (
            InstanceIndex,
            build_instance_index,
        )

        wanted = [n for n in names if n]
        if not wanted:
            return InstanceIndex()
        conn, owned = None, False
        try:
            conn, owned = self._name_read_connection()
            if conn is None:
                return InstanceIndex()
            return build_instance_index(conn, socket=socket, names=wanted)
        except Exception as exc:  # noqa: BLE001
            logger.debug("instance_index_for_listing_threw", error=str(exc))
            return InstanceIndex()
        finally:
            if conn is not None and owned:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    def _identity_for_instance(self, tmux_name, epoch):
        from src.core.session_store import identity_for_instance

        if not tmux_name or epoch is None:
            return None
        conn = None
        try:
            conn = self._writable_datastore_connection()
            if conn is None:
                return None
            return identity_for_instance(
                conn,
                socket=self._tmux_socket_name(),
                name=tmux_name,
                epoch=epoch,
            )
        except Exception as exc:
            logger.debug("session_identity_instance_read_threw", error=str(exc))
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _label_for_instance(self, tmux_name, epoch):
        from src.core.session_label import label_for_instance

        if not tmux_name or epoch is None:
            return None
        conn = None
        try:
            conn = self._writable_datastore_connection()
            if conn is None:
                return None
            return label_for_instance(
                conn,
                socket=self._tmux_socket_name(),
                name=tmux_name,
                epoch=epoch,
            )
        except Exception as exc:
            logger.debug("session_label_instance_read_threw", error=str(exc))
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def reconcile_lifecycle(
        self,
        listing: TmuxListing,
        pane_status: Optional[StatusMap] = None,
    ) -> "ReconcileOutcome":
        """Fold one tmux listing into the stored ``lifecycle`` column.

        Description: the bridge between the live probe and the datastore,
          and the ONLY place this class writes ``lifecycle``. It is called
          from :meth:`list_attachable_sessions` on the branch where the
          probe ANSWERED, because that listing is already a complete
          enumeration of the socket, the home screen pays for it on every
          load anyway, and a second scheduled probe would only add a
          second way to be wrong.

          It hands the socket the probe was ACTUALLY bound to, never the
          configured one - the two can disagree under a pinned test
          backend, and reconciling socket A's rows against socket B's
          listing would reap every one of them.

          NEVER RAISES. A datastore that is absent, locked or unreadable
          is a reason to leave every stored row exactly as it is, not a
          reason to fail the launcher's session list. The failure is
          logged and the outcome says it was not evaluated.

          The transaction is owned here, not in
          :func:`~src.core.session_lifecycle.reconcile_from_listing`,
          which matches ``session_identity.record_instance``. The commit
          is skipped entirely when nothing was reaped, so the common case
          - a poll where every session is still alive - opens the file,
          runs one SELECT and writes nothing at all.
        Inputs: listing (TmuxListing) - the probe result; its ``ok`` and
          ``complete`` are re-read inside the reconciler, which is where
          the gate lives. pane_status (StatusMap | None) - the bulk
          ``list-panes -a`` map from the SAME probe backend, which lets
          the reconciler also reap a session tmux still lists but whose
          pane it measured dead. None disables that rung; its own
          completeness and its own socket are gated inside
          ``session_pane_death``, not here.
        Output: ReconcileOutcome - ``evaluated=False`` whenever the probe
          could not answer, the listing was partial, or the datastore
          could not be opened. Those are three different reasons and none
          of them is "nothing died".
        Example: mgr.reconcile_lifecycle(listing).changed
        """
        from src.core.session_lifecycle import (
            RECONCILE_NO_TABLE,
            ReconcileOutcome,
            reconcile_from_listing,
        )

        conn = self._writable_datastore_connection()
        if conn is None:
            return ReconcileOutcome(
                outcome=RECONCILE_NO_TABLE,
                evaluated=False,
                detail="datastore not available for writing",
            )
        try:
            outcome = reconcile_from_listing(
                conn,
                listing=listing,
                socket=self._probe_health.socket or self._tmux_socket_name(),
                pane_status=pane_status,
            )
            if outcome.changed:
                conn.commit()
                logger.info(
                    "session_lifecycle_reconciled",
                    stopped=len(outcome.stopped_uuids),
                    pane_dead_stopped=outcome.pane_dead_stopped,
                    examined=outcome.examined,
                    session_uuids=list(outcome.stopped_uuids),
                )
            return outcome
        except sqlite3.Error as exc:
            logger.warning(
                "session_lifecycle_reconcile_failed",
                error=str(exc),
                note="stored lifecycles left untouched",
            )
            return ReconcileOutcome(
                outcome=RECONCILE_NO_TABLE,
                evaluated=False,
                detail=f"datastore error: {exc}",
            )
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def list_attachable_sessions_with_socket(self):
        listing = self.list_attachable_sessions()
        return self._probe_health.socket, listing

    def list_attachable_sessions(self) -> TmuxListing:
        from src.core.tmux_socket_resolution import (
            configured_tmux_socket_name,
            resolve_probe_socket,
        )

        def _list_for_socket(socket_name: str):
            probe = build_backend(
                settings,
                session_id="__probe__",
                working_dir=Path.home(),
                on_output=None,
                socket_name_override=socket_name,
            )
            actual_socket = getattr(probe, "socket_name", None) or socket_name
            self._probe_health.record_socket(actual_socket)
            listing = coerce_listing(
                probe.list_attachable_sessions(
                    owned_names=set(self._owned.names),
                    owned_instances=self._owned.instances(),
                )
            )
            return actual_socket, listing

        configured = configured_tmux_socket_name(settings)
        socket_name, listing = resolve_probe_socket(
            self, configured, _list_for_socket
        )
        self._probe_health.record_socket(socket_name)
        if not listing.ok:
            logger.warning(
                "attachable_listing_unavailable",
                reason=listing.reason,
                detail=listing.detail,
            )
            self._probe_health.record_failure(
                reason=listing.reason, detail=listing.detail
            )
            return listing
        self._probe_health.record_success()
        self.reconcile_lifecycle(listing)
        rows = listing.sessions
        status_probe = build_backend(
            settings,
            session_id="__probe__",
            working_dir=Path.home(),
            on_output=None,
            socket_name_override=socket_name,
        )
        status_listing = (
            coerce_listing(status_probe.list_pane_status_all())
            if hasattr(status_probe, "list_pane_status_all")
            else TmuxListing.answered([])
        )
        if not status_listing.ok:
            logger.warning(
                "attachable_status_map_unavailable",
                reason=status_listing.reason,
                note="attachable rows fall back to unknown activity status",
            )
        # did not answer
        status_map = status_map_from_listing(
            status_listing, socket=self._probe_health.socket
        )
        self.reconcile_lifecycle(listing, status_map)
        rows = listing.sessions
        wrappers = _configured_wrappers()
        instance_index = self._instance_index_for_listing(
            socket=self._tmux_socket_name(),
            names=[r.get("name") for r in rows],
        )
        for row in rows:
            name = row.get("name")
            if name:
                row["pinned_theme"] = self._theme_store.get_pin(name)
                row["label"] = instance_index.label(
                    name, row.get("created_at_epoch")
                )
                identity = instance_index.identity(
                    name, row.get("created_at_epoch")
                )
                row["session_row_id"] = identity["id"] if identity else None
                row["parent_session_id"] = (
                    identity["parent_session_id"] if identity else None
                )
                status_row = status_map.get(name)
                raw_tmux_status = status_row["status"] if status_row else STATUS_UNKNOWN
                row_epoch = unread_identity.remember(
                    self._unread_epochs, name, unread_identity.epoch_of_row(row))
                unread = self._is_unread(name, row_epoch, unread_follow_up.remember_row(
                    self._unread_rows, name, row_epoch, row["session_row_id"]))
                row["status"] = map_tmux_fallback(raw_tmux_status, unread=unread)
                row["unread"] = unread
                probe_socket = self._tmux_socket_name()
                launch = instance_index.stored_launch(
                    name, row.get("created_at_epoch")
                )
                from_process = False
                if launch.known:
                    effective_agent_type = launch.agent_type
                    from_fingerprint = False
                    from_process = launch.from_process
                else:
                    effective_agent_type = self._fingerprint_agent_type_for_listing(
                        socket=probe_socket,
                        name=name,
                        epoch=row.get("created_at_epoch"),
                    )
                    from_fingerprint = True
                row["agent_type"] = effective_agent_type
                display_family, display_family_source = resolve_family_for_display(
                    effective_agent_type,
                    wrappers,
                    from_fingerprint=from_fingerprint,
                    from_process=from_process,
                )
                row["agent_family"] = display_family.name if display_family else None
                row["agent_family_source"] = display_family_source
                row["agent_wrapper_label"] = resolve_wrapper_for_display(
                    effective_agent_type,
                    wrappers,
                    from_fingerprint=from_fingerprint,
                ).label
        return TmuxListing.answered(rows, reason=listing.reason,
                                    detail=listing.detail,
                                    refused_rows=listing.refused_rows)

    async def adopt_external_session(self, name: str, **kwargs: Any) -> dict:
        async with self._adopt_locks.hold(name):
            try:
                return await self._adopt_external_session_locked(name, **kwargs)
            finally:
                self._registry.discard_parked(name)

    async def _adopt_external_session_locked(
        self,
        name: str,
        confirm_detach: bool = False,
        initial_cols: Optional[int] = None,
        initial_rows: Optional[int] = None,
    ) -> dict:
        _ = confirm_detach

        from src.core.session_adopt_dead_gate import PERSIST_PANE_DEAD
        from src.core.session_adopt_persist import (
            PERSIST_SESSION_GONE,
            AdoptTargetGoneError,
        )

        adopt_persist = self.persist_adoption(name)
        if adopt_persist.outcome in (PERSIST_SESSION_GONE, PERSIST_PANE_DEAD):
            raise AdoptTargetGoneError(
                adopt_persist.detail or "that session is no longer there"
            )

        adopt_identity = self._adopt_identity_for(name, adopt_persist.epoch)
        adopt_session_id = adopt_identity.session_id
        adopt_identity.log_if_rekeyed(name)

        async with hold_pending_registration(
            self._pending_agent_registration, adopt_session_id, name
        ):
            for stale_id in self._registry.registered_ids_for_tmux_name(
                name, also=adopt_session_id
            ):
                if stale_id == adopt_session_id:
                    self._registry.park_viewers(name, stale_id)
                await session_ghost_reap.drop_registration(
                    self, stale_id, reason="adopt_one_pane_one_registration"
                )

            if adopt_persist.epoch is not None:
                self._instance_epochs[adopt_session_id] = adopt_persist.epoch
            if not adopt_persist.persisted:
                logger.warning(
                    "adopt_not_persisted",
                    session=name,
                    outcome=adopt_persist.outcome,
                    detail=adopt_persist.detail,
                    note=(
                        "the session is being adopted but the claim was not "
                        "recorded, so its badge is not durable yet"
                    ),
                )

            working_dir = await self._resolve_external_cwd(name)

            from src.core.tmux_backend import PaneDeadError, TmuxBackend

            backend = TmuxBackend.for_external(
                session_name=name,
                working_dir=working_dir,
                on_output=self._make_output_handler(adopt_session_id),
                viewer_probe=self._make_viewer_probe(adopt_session_id),
                socket_name=settings.load_auth_config().session.tmux_socket_name,
                scrollback_lines=settings.load_auth_config().session.scrollback_lines,
            )

            # could not
            try:
                await backend.attach_existing(needs_pipe_setup=True)
            except PaneDeadError as exc:
                raise AdoptTargetGoneError(str(exc)) from exc

            if initial_cols and initial_rows:
                try:
                    backend.resize(initial_cols, initial_rows)
                    logger.info(
                        "adopted_session_resized",
                        session=name,
                        cols=initial_cols,
                        rows=initial_rows,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    logger.warning(
                        "adopted_session_resize_failed",
                        session=name,
                        cols=initial_cols,
                        rows=initial_rows,
                        error=str(exc),
                    )

            try:
                fifo_start_offset = os.path.getsize(str(backend._pipe_path))
            except OSError as exc:
                logger.warning(
                    "adopt_fifo_offset_read_failed",
                    session=name,
                    error=str(exc),
                )
                fifo_start_offset = 0

            scrollback = with_cursor_restore(
                backend.capture_scrollback(), backend.pane_cursor_position())

            sb_b64 = (
                base64.b64encode(scrollback).decode("ascii")
                if scrollback else ""
            )

            from src.core.agent_fingerprint import detect_agent_type
            try:
                scrollback_text = scrollback.decode("utf-8", errors="replace")
            except Exception:
                scrollback_text = ""
            detected_agent_type = detect_agent_type(scrollback_text)
            logger.info(
                "agent_fingerprint_detected",
                session=name,
                agent_type=detected_agent_type,
            )

            # nothing at all
            if detected_agent_type and adopt_persist.session_uuid:
                display_family, _display_source = resolve_family_for_display(
                    detected_agent_type,
                    _configured_wrappers(),
                    from_fingerprint=True,
                )
                if display_family is not None:
                    self._persist_fingerprint_family(
                        session_uuid=adopt_persist.session_uuid,
                        agent_family=display_family.name,
                    )

            prior_pin = self._theme_store.resolve_project_theme(working_dir, name)
            adopted_session = Session(
                id=adopt_session_id,
                tmux_created_epoch=adopt_persist.epoch,
                pty_pid=getattr(backend, "pid", None),
                working_dir=str(working_dir),
                status=SessionStatus.RUNNING,
                created_at=datetime.utcnow(),
                last_activity=datetime.utcnow(),
                agent_type=detected_agent_type,
                agent_type_via_fingerprint=True,
                pinned_theme=prior_pin,
                tmux_session=name,
            )
            self._registry.register(adopted_session, backend)

            if adopt_identity.rekeyed and self.hook_tokens.get(adopt_session_id):
                self.hook_tokens.keep(adopt_session_id, tmux_name=name)
            else:
                self.hook_tokens.mint(adopt_session_id, tmux_name=name)
            spawn_env = self.get_env_for_spawn(adopt_session_id)
            try:
                await backend.set_session_environment(
                    name, spawn_env, note="adopt_set_environment")
            except Exception as exc:
                logger.debug(
                    "adopt_set_environment_failed",
                    session=name,
                    error=str(exc),
                )
            self._save_session_metadata(adopted_session)

            self._sidecars.set_fifo_offset(adopt_session_id, fifo_start_offset)

            logger.info(
                "session_adopted_external",
                session=name,
                working_dir=str(working_dir),
                fifo_start_offset=fifo_start_offset,
                scrollback_bytes=len(scrollback),
            )

            return {
                "session": adopted_session,
                "initial_scrollback_b64": sb_b64,
                "fifo_start_offset": fifo_start_offset,
            }

    async def destroy_external_session(self, name: str) -> dict:
        from src.core.tmux_backend import _safe_target, DEFAULT_SOCKET_NAME, tmux_argv_prefix

        if parse_remote_session_id(name) is not None:
            return await remote_sessions.destroy_external(self, name)
        for sid, backend in self._registry.backends.items():
            if getattr(backend, "tmux_session", None) == name and not is_remote_backend(backend):
                raise ValueError(
                    f"{name!r} is a currently-active session (id={sid!r}); "
                    "use DELETE /sessions to destroy it"
                )

        target = _safe_target(name)

        try:
            socket_name = settings.load_auth_config().session.tmux_socket_name
        except Exception:
            socket_name = DEFAULT_SOCKET_NAME

        logger.info("destroying_external_session", name=name, socket=socket_name)

        proc = await asyncio.create_subprocess_exec(
            *tmux_argv_prefix(socket_name), "kill-session", "-t", target,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        rc = proc.returncode or 0
        invalidate_pane_listing(socket_name)

        if name in self._owned.names:
            self._owned.names.discard(name)
            try:
                self._save_session_metadata()
            except Exception as exc:
                logger.warning(
                    "owned_tmux_sessions_save_after_external_destroy_failed",
                    name=name,
                    error=str(exc),
                )

        self._theme_store.discard_pin(name)

        if rc == 0:
            logger.info("external_session_destroyed", name=name)
            return {"name": name, "killed": True, "already_gone": False}

        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if "can't find session" in stderr_text.lower() or "session not found" in stderr_text.lower():
            logger.info(
                "external_session_already_gone", name=name, stderr=stderr_text
            )
            return {"name": name, "killed": False, "already_gone": True}

        logger.error(
            "external_session_destroy_failed",
            name=name,
            returncode=rc,
            stderr=stderr_text,
        )
        raise RuntimeError(
            f"tmux kill-session for {name!r} failed (rc={rc}): {stderr_text}"
        )

    def _resume_target_for_tmux_name(self, name: str, socket_name: str):
        from src.core.session_resume_target import resume_target_from_row

        conn = self._datastore_connection()
        if conn is None:
            return resume_target_from_row(None, row_read_ok=False)
        try:
            from src.core.session_store import (
                identity_for_live_name,
                sessions_table_ready,
            )

            if not sessions_table_ready(conn):
                return resume_target_from_row(None, row_read_ok=False)
            identity = identity_for_live_name(
                conn, socket=socket_name, name=name
            )
            if identity is None:
                return resume_target_from_row(None, row_read_ok=True)
            row = conn.execute(
                "SELECT claude_session_uuid, agent_family, working_dir, title, "
                "session_uuid, last_work_at FROM sessions WHERE id = ?",
                (int(identity["id"]),),
            ).fetchone()
            target = resume_target_from_row(
                dict(row) if row is not None else None, row_read_ok=True
            )
            from src.core.sessions.session_unstarted import (
                downgrade_if_unstarted,
                row_has_recorded_work,
            )

            row_facts = dict(row) if row else {}
            return downgrade_if_unstarted(self._codex_adopted_resume_upgrade(
                target,
                name,
                row_working_dir=row_facts.get("working_dir"),
            ), name, row_facts.get("working_dir"), recorded_work=row_has_recorded_work(
                row_facts.get("last_work_at"), row_facts.get("session_uuid"),
                settings.get_state_dir()))
        except sqlite3.Error as exc:
            logger.warning(
                "restart_resume_target_read_failed", name=name, error=str(exc)
            )
            return resume_target_from_row(None, row_read_ok=False)
        finally:
            try:
                conn.close()
            except sqlite3.Error:  # noqa: BLE001
                pass

    def _codex_adopted_resume_upgrade(
        self,
        target: "ResumeTarget",
        name: str,
        *,
        row_working_dir: Optional[str] = None,
    ) -> "ResumeTarget":
        from src.core.attention.evidence import FAMILY_CODEX
        from src.core.session_resume_target import (
            CONVERSATION_NONE_RECORDED,
            upgrade_codex_adopted_target,
        )

        if (
            target.outcome != CONVERSATION_NONE_RECORDED
            or target.family != FAMILY_CODEX
        ):
            return target

        working_dir: Optional[str] = None
        for session in self._registry.sessions.values():
            if getattr(session, "tmux_session", None) == name and not self._is_remote_sid(session.id):
                working_dir = getattr(session, "working_dir", None)
                break
        if not working_dir:
            working_dir = row_working_dir

        try:
            from src.core.attention.codex_gather import DEFAULT_CODEX_HOME
            from src.core.attention.codex_stores import resolve_primary_uuid

            upgraded = upgrade_codex_adopted_target(
                target,
                working_dir=working_dir,
                pick=lambda wd: resolve_primary_uuid(
                    DEFAULT_CODEX_HOME, pane_current_path=wd, pane_title=""
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "restart_codex_adopted_pick_failed",
                name=name,
                error=str(exc),
                note="codex store unreadable; the restart resumes fresh",
            )
            return target

        if upgraded.claude_session_uuid:
            logger.info(
                "restart_codex_adopted_pick_resolved",
                name=name,
                claude_session_uuid=upgraded.claude_session_uuid,
                note="adopted codex pane resumed via a restart-time pick",
            )
        else:
            logger.info(
                "restart_codex_adopted_pick_none",
                name=name,
                note=(
                    "no unambiguous codex conversation for this pane's cwd; "
                    "the restart starts a fresh conversation"
                ),
            )
        return upgraded

    def _agent_command_for_tmux_name(
        self,
        name: str,
        *,
        socket_name: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Command this app would launch for the session with this tmux name.

        Description: looks up the in-memory ``Session`` carrying this tmux
            name and re-derives its launch command through
            ``Settings.get_agent_command`` using the ``agent_type`` and
            ``model`` recorded at create time.

            RE-DERIVED, NOT REPLAYED: a restart runs the CURRENT command for
            the agent type (a new wrapper path, a new CLI location), carrying
            the conversation through ``extra_args`` (``--resume``) via
            ``get_agent_command``'s own quoting, never by concatenation (see
            ``src/core/session_resume_target.py``). None is a real answer: this
            app has no record of what the session runs (an external session).
            The agent_type comes from ``_stored_agent_type_for_tmux_name``, as
            in the preview. A row WITH a launch record goes through
            ``restart_seam`` instead; this is the legacy path.

        Inputs:
            name: literal tmux session name.
            socket_name: tmux socket the session lives on, needed to key
                the row read. None falls back to memory alone, which is
                the old behaviour and is only right when the caller
                genuinely has no socket.
            extra_args: arguments appended to the wrapped CLI, quoted at
                every boundary by ``get_agent_command``. The restart path
                passes ``['--resume', '<uuid>']``; None adds nothing and
                is what a session with no recorded conversation gets.

        Output:
            Optional[str]: shell command string, or None when this app has
                no record for that name or the config could not be read.

        Example:
            >>> mgr._agent_command_for_tmux_name("cloude_api")
            "zsh -c 'source ~/.zshrc ...; keyc'"
        """
        if socket_name:
            agent_type = self._stored_agent_type_for_tmux_name(
                name, socket_name
            )
        else:
            agent_type = None
            for session in self._registry.sessions.values():
                if getattr(session, "tmux_session", None) == name \
                        and not self._is_remote_sid(session.id):
                    agent_type = getattr(session, "agent_type", None)
                    break
        if not agent_type:
            return None

        try:
            return settings.pane_launch_command(
                agent_type,
                model=self._model_for_tmux_name(name),
                extra_args=extra_args,
            )
        except Exception as exc:
            logger.warning(
                "respawn_agent_command_unresolved",
                tmux_name=name,
                agent_type=agent_type,
                error=str(exc),
            )
            return None

    async def respawn_session(
        self,
        name: str,
        *,
        socket_name: Optional[str] = None,
        agent_type: Optional[str] = None,
        live_restart_confirmed: bool = False,
        require_agent_resume: bool = False,
        account_id: Optional[str] = None, account_pinned: bool = False, persist_account: bool = True,
        live_restart_reason: Optional[str] = None, start_directory: Optional[str] = None,
    ) -> dict:
        """Restart the agent inside a dead session, keeping the session.

        Description: the server half of the launcher's restart control.
            ``remain-on-exit`` means a session whose agent exited still
            exists - window, pane, pane id, scrollback and the app's
            ``pipe-pane`` all intact - so this puts a process back into
            that pane rather than building anything new.

            IDENTITY IS PRESERVED BY CONSTRUCTION, NOT BY COPYING FIELDS.
            The durable identity of a session row is the instance triple
            ``(tmux_socket, tmux_name, tmux_created_epoch)``, and
            ``#{session_created}`` belongs to the SESSION, not to the
            pane's process - a respawn does not change it. So every
            existing lookup keeps matching the SAME row and its
            ``session_uuid``, ``origin``, ``project_id``, ``pinned_theme``,
            unread state and title are untouched because nothing writes
            them. This method issues NO database write at all.

            THAT IS ALSO WHAT SEPARATES IT FROM A FORK. A fork deliberately
            mints a new row and sets ``parent_session_id`` / ``fork_kind``.
            A respawn cannot mint one, because there is no new instance for
            a row to key on, and it never touches either column.

            IT NOW WRITES EXACTLY ONE COLUMN, AND ONLY WHEN ASKED TO.
            When ``agent_type`` names a wrapper the user picked in the
            restart picker, and the restart came back with a process
            VERIFIED alive, ``sessions.agent_type`` is updated so the
            next restart remembers the choice. Nothing else is written -
            no lineage, no origin, no identity column - so a restart is
            still not a fork. With no ``agent_type`` this method issues
            no database write at all, exactly as before. The rules for
            validating and persisting the choice live in
            ``src/core/session_agent_choice.py``, not here.

            AN ALREADY-BOUND BACKEND IS REUSED, not rebuilt: the existing
            ``pipe-pane`` survives the respawn (measured) and keeps
            streaming to the open terminal; a second backend for the same
            pane would leave two readers on one file.

        Inputs:
            name: literal tmux session name as shown in the session list.
            socket_name: tmux socket override. Internal/test use only -
                the HTTP route never passes it, so a client cannot aim
                this at another socket. Defaults to the configured one.
            agent_type: id of a configured launch wrapper to restart
                THIS session with, replacing whatever it was launched
                with. None (the default) keeps the existing behaviour
                exactly. An id that is not configured is REFUSED with a
                ValueError rather than resolved to the default wrapper -
                a picker that substitutes a different agent is worse.
            require_agent_resume: True ONLY from the unattended limit restart (#521): refuse unless the agent resumes.
            live_restart_reason: a named unattended reason (``session_respawn.LIVE_RESTART_REASONS``) or None.
            start_directory: the session move's new folder (``respawn-pane -c``, #254), else None.
            account_id: the claude account the restart dialog chose to launch
                on (ValueError when it cannot start and
                resume). None keeps the session's pinned account, else the
                globally active one (``account_switch/restart_account.py``).
            account_pinned: the dialog's "always restart this session on this account" box, applied after success. persist_account=False (the limit rotation, #2035): never write or clear the pin.
            live_restart_confirmed: True ONLY when the user deliberately
                asked to replace what is running in a pane that is
                ALIVE, having been shown the confirmation that says the
                process in it is killed. False (the default) leaves the
                behaviour of every existing caller untouched: a live pane
                still answers ``not_dead`` and nothing is destroyed.

                IT IS A PERMISSION, SO IT ONLY EVER TRAVELS FORWARD. No
                prediction produces it, no preview returns it, and
                nothing derives it from ``pane_state`` - the request
                carries it or the restart does not kill.

        Output:
            dict: ``{"name", "kind", "ok", "detail", "command",
                "chosen", "agent_type", "agent_type_persisted",
                "session_id", "session_uuid"}``. The last two are read
                back AFTER the restart and are what lets the client
                reopen the SAME session rather than hunt for it.
                ``ok`` False with a ``kind`` of ``cannot_determine`` is a
                normal, successful API call reporting that the pane could
                not be read - it is not an error.

        Raises:
            ValueError: ``name`` contains a tmux target separator, or
                ``agent_type`` is not a configured wrapper, or the
                wrapper list could not be read so the id could not be
                checked. The last two are separate sentences - "that is
                not a wrapper" and "I could not tell whether it is" are
                different answers and the user is told which.

        Example:
            >>> await mgr.respawn_session("cloude_api")
            {'name': 'cloude_api', 'kind': 'agent', 'ok': True, ...}
            >>> await mgr.respawn_session("cloude_api",
            ...                           agent_type="claude-chrome")
            {'name': 'cloude_api', 'kind': 'agent', 'chosen': True, ...}
        """
        from src.core.tmux_backend import DEFAULT_SOCKET_NAME, TmuxBackend, _safe_target

        if parse_remote_session_id(name) is not None:
            return await remote_sessions.respawn_remote(
                self, name, agent_type=agent_type, live_restart_confirmed=live_restart_confirmed)
        _safe_target(name)

        if socket_name is None:
            try:
                socket_name = settings.load_auth_config().session.tmux_socket_name
            except Exception:
                socket_name = DEFAULT_SOCKET_NAME

        await project_home.require_active_tmux(socket_name, name)

        save_triggers.schedule_for_instance(
            socket_name, name, None, save_triggers.EVENT_RESTART)

        from src.core.swarm.launch import restart_resume_args

        resume_target = self._resume_target_for_tmux_name(name, socket_name)
        resume_args = restart_resume_args(socket_name, name, resume_target)

        replayed = await restart_seam.replay_for_restart(
            settings, self._datastore_connection(), socket_name, name, model=self._model_for_tmux_name(name),
            extra_args=resume_args, picked=bool(agent_type and str(agent_type).strip()))
        agent_command = replayed.command if replayed else self._agent_command_for_tmux_name(
            name, socket_name=socket_name, extra_args=resume_args
        )

        chosen_command: Optional[str] = None
        chosen_type: Optional[str] = None
        if agent_type and str(agent_type).strip():
            from src.core.session_agent_choice import validate_agent_choice

            choice = validate_agent_choice(
                settings,
                agent_type,
                model=self._model_for_tmux_name(name),
                extra_args=resume_args,
            )
            if not choice.accepted:
                logger.info(
                    "respawn_agent_choice_refused",
                    name=name,
                    agent_type=choice.agent_type,
                    verdict=choice.verdict,
                )
                raise ValueError(choice.detail)
            chosen_command = choice.command
            chosen_type = choice.agent_type

        backend = None
        env_session_id: Optional[str] = None
        for candidate_id, candidate in self._registry.backends.items():
            if getattr(candidate, "tmux_session", None) == name and not is_remote_backend(candidate):
                backend = candidate
                env_session_id = candidate_id
                break

        if backend is None or not hasattr(backend, "respawn"):
            backend = TmuxBackend.for_external(
                session_name=name,
                working_dir=Path(settings.default_working_dir).expanduser(),
                on_output=None,
                socket_name=socket_name,
            )

        logger.info(
            "respawn_session_request",
            name=name,
            socket=socket_name,
            has_agent_record=agent_command is not None,
            conversation=resume_target.outcome,
        )

        # active account
        spawn_env = self.get_env_for_spawn(env_session_id) if env_session_id else None
        from src.core.agent_families import resolve_agent_type
        from src.core.attention.restart_floor import restart_bracket

        resume_family = (replayed.display.harness if replayed and replayed.display else resolve_agent_type(
            chosen_type or self._stored_agent_type_for_tmux_name(name, socket_name), settings.load_auth_config().agents.wrappers)[0].name)
        account_plan = await restart_account.resolve(
            launch_env._config_path(), session_uuid=self._row_identity_for_tmux_name(name, socket_name).get("session_uuid"),
            family=resume_family, requested=account_id, pinned_box=account_pinned, persist=persist_account)
        if agent_command or chosen_command:
            refusal = await launch_env.restart_refusal(socket_name, name, claude_account=account_plan.account_id)
            if refusal:
                # active account
                return {
                    "name": name,
                    "kind": "cannot_determine",
                    "ok": False,
                    "detail": refusal,
                    "command": None,
                    "chosen": False,
                    "agent_type": chosen_type,
                    "agent_type_persisted": False,
                    "session_id": env_session_id,
                    "session_uuid": None,
                    "killed_live_pane": False,
                    "identity_status": "unchecked",
                    "conversation": resume_target.outcome,
                }
        if spawn_env is not None and (agent_command or chosen_command):
            spawn_env = await launch_env.respawn_pane_env(spawn_env, claude_account=account_plan.account_id)
        if replayed and replayed.staged:
            spawn_env = {**(spawn_env or {}), **replayed.staged}

        with restart_bracket(self._attention_watcher, backend, env_session_id) as window:
            try:
                result = await backend.respawn(
                    agent_command=agent_command,
                    chosen_agent_command=chosen_command,
                    chosen_agent_type=chosen_type,
                    resume_outcome=resume_target.outcome,
                    live_restart_confirmed=bool(live_restart_confirmed),
                    spawn_env=spawn_env,
                    require_agent_resume=require_agent_resume,
                    resume_family=resume_family, live_restart_reason=live_restart_reason,
                    **({"start_directory": start_directory} if start_directory else {}))
                window.replaced = result.ok or bool(result.killed_live_pane)
            finally:
                if replayed and replayed.staged:
                    await create_seam.scrub_staging(backend, replayed.staged)
        from src.api import session_account_listing

        session_account_listing.invalidate(name)

        identity_status = self._reconcile_restart_identity(
            name=name, socket_name=socket_name, result=result
        )

        persisted = False
        if result.ok and result.chosen and chosen_type:
            persisted = self._persist_respawn_agent_type(
                name=name, socket_name=socket_name, agent_type=chosen_type
            )

        identity = self._row_identity_for_tmux_name(name, socket_name)
        account_pin = await restart_account.persist(
            launch_env._config_path(), identity.get("session_uuid"), account_plan) if result.ok else None
        if result.ok and result.kind == "agent":
            await restart_seam.write_record(
                settings, self._writable_datastore_connection(), replayed, chosen_type, identity.get("session_uuid"),
                model=self._model_for_tmux_name(name), extra_args=resume_args, account_id=account_plan.account_id)

        return {
            "name": name,
            "kind": result.kind,
            "ok": result.ok,
            "detail": result.detail,
            "command": result.command,
            "chosen": result.chosen,
            "agent_type": chosen_type,
            "agent_type_persisted": persisted,
            "session_id": identity.get("session_id"),
            "session_uuid": identity.get("session_uuid"),
            "account_id": account_plan.account_id,
            "account_pin": account_pin,
            "killed_live_pane": bool(result.killed_live_pane),
            "identity_status": identity_status,
            "conversation": result.conversation,
        }

    def _reconcile_restart_identity(
        self, *, name: str, socket_name: str, result
    ) -> str:
        """Keep the row keyed on the instance the restart left behind.

        Description: the database half of the live-restart identity
            check. Does nothing at all unless the restart actually killed
            a pane; on tmux 3.7c the epoch does not move even then, so
            the expected answer is ``unchanged`` with no write. See
            ``src/core/session_instance_rekey.py`` for why it is measured
            rather than assumed, and for why the third outcome is not the
            first.

        Inputs:
            name: literal tmux session name, unchanged by the restart.
            socket_name: tmux socket the session lives on.
            result: the ``RespawnResult`` the backend returned, carrying
                both ``#{session_created}`` readings.

        Output:
            str: one of the ``IDENTITY_*`` constants in
                ``src.core.session_instance_rekey``.

        Example:
            >>> mgr._reconcile_restart_identity(name='cloude_api',
            ...     socket_name='cloude', result=res)
            'unchanged'
        """
        from src.core.session_instance_rekey import (
            IDENTITY_UNCHECKED,
            reconcile_instance_epoch,
        )

        if not getattr(result, "killed_live_pane", False):
            return IDENTITY_UNCHECKED

        conn = self._writable_datastore_connection()
        try:
            status, _rows = reconcile_instance_epoch(
                conn,
                socket=socket_name,
                tmux_name=name,
                epoch_before=getattr(result, "epoch_before", None),
                epoch_after=getattr(result, "epoch_after", None),
            )
            return status
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:  # noqa: BLE001
                    pass

    async def restart_preview(
        self, name: str, *, socket_name: Optional[str] = None
    ) -> "RestartPreview":
        """What restarting this session would do, WITHOUT doing it.

        Description: the read-only half of the restart path, and the one
            thing that lets the picker warn honestly. It probes the pane
            once (a ``tmux list-panes``, a read), reads the session's
            recorded ``agent_type`` from the ROW rather than from memory
            (an adopted session's in-memory copy carries None while its
            row records the wrapper exactly), resolves every configured
            wrapper to a command, and runs the SAME ladder the action
            runs against all of it.

            NOTHING IS SPAWNED, NOTHING IS WRITTEN, and no backend is
            adopted: when the session is not open in the app a bare
            handle is built purely to issue the read and is discarded.

            THE SHELL LANDMINE IS WHAT THIS IS FOR. A pane with an empty
            ``#{pane_start_command}`` lands on ``shell``, and the
            preview's ``unchanged`` plan says so in a sentence before the
            user commits to anything.

        Inputs:
            name: literal tmux session name as shown in the session list.
            socket_name: tmux socket override, internal/test use only.

        Output:
            RestartPreview: the baseline plan plus one predicted outcome
                per configured wrapper. ``wrappers_status`` is
                ``unavailable`` when the wrapper list could not be read,
                which is NOT the same as an empty list.

        Raises:
            ValueError: ``name`` contains a tmux target separator.

        Example:
            >>> (await mgr.restart_preview("cloude_api")).unchanged.kind
            'shell'
        """
        from src.core.session_agent_choice import resolve_wrapper_offers
        from src.core.session_respawn import resume_uuid_in
        from src.core.session_restart_preview import build_restart_preview
        from src.core.tmux_backend import (
            DEFAULT_SOCKET_NAME,
            TmuxBackend,
            _safe_target,
        )

        _safe_target(name)

        if socket_name is None:
            try:
                socket_name = settings.load_auth_config().session.tmux_socket_name
            except (OSError, ValueError, AttributeError):
                socket_name = DEFAULT_SOCKET_NAME

        backend = None
        for candidate in self._registry.backends.values():
            if getattr(candidate, "tmux_session", None) == name and not is_remote_backend(candidate):
                backend = candidate
                break
        if backend is None or not hasattr(backend, "probe_respawn"):
            backend = TmuxBackend.for_external(
                session_name=name,
                working_dir=Path(settings.default_working_dir).expanduser(),
                on_output=None,
                socket_name=socket_name,
            )

        probe_ok, pane_dead, start_command = await backend.probe_respawn()

        stored_type = self._stored_agent_type_for_tmux_name(name, socket_name)
        model = self._model_for_tmux_name(name)

        from src.core.swarm.launch import restart_resume_args

        resume_target = self._resume_target_for_tmux_name(name, socket_name)
        resume_args = restart_resume_args(socket_name, name, resume_target, preview=True)

        stored_command: Optional[str] = None
        launch_display: Optional[dict] = None
        if stored_type:
            try:
                replayed = await restart_seam.replay_for_restart(
                    settings, self._datastore_connection(), socket_name, name, model=model,
                    extra_args=resume_args, preview=True)
                if replayed is not None:
                    stored_command, launch_display = replayed.command, vars(replayed.display)
                else:
                    stored_command = settings.pane_launch_command(
                        stored_type, model=model, extra_args=resume_args
                    )
            except restart_seam.LaunchProfileNotFound as exc:
                launch_display = {"missing_profile": exc.profile_id, "codes": list(exc.codes)}
            except (ValueError, OSError, AttributeError) as exc:
                logger.info(
                    "restart_preview_stored_command_unresolved",
                    name=name,
                    agent_type=stored_type,
                    error=str(exc),
                )

        offers = resolve_wrapper_offers(
            settings, model=model, extra_args=resume_args
        )

        presence_by_uuid: dict = {}
        for candidate in (resume_uuid_in(start_command),
                          resume_target.claude_session_uuid):
            if not candidate or candidate in presence_by_uuid:
                continue
            from src.core.agent_families import resolve_agent_type
            from src.core.session_transcript_presence import (
                family_conversation_presence,
            )

            presence = family_conversation_presence(
                resolve_agent_type(stored_type, settings.load_auth_config().agents.wrappers)[0].name,
                candidate,
                working_dir=str(Path(settings.default_working_dir).expanduser()),
            )
            presence_by_uuid[candidate] = (presence.outcome, presence.detail)

        logger.info(
            "restart_preview",
            name=name,
            probe_ok=probe_ok,
            pane_dead=pane_dead,
            stored_agent_type=stored_type,
            offers=len(offers) if offers is not None else None,
            conversation=resume_target.outcome,
        )

        return dataclasses.replace(build_restart_preview(
            name=name,
            probe_ok=probe_ok,
            pane_dead=pane_dead,
            pane_start_command=start_command,
            stored_agent_type=stored_type,
            stored_agent_command=stored_command,
            offers=offers,
            presence_by_uuid=presence_by_uuid,
            resume_outcome=resume_target.outcome,
        ), launch_display=launch_display)

    def _stored_agent_type_for_tmux_name(
        self, name: str, socket_name: str
    ) -> Optional[str]:
        conn = self._datastore_connection()
        if conn is not None:
            try:
                from src.core.session_store import (
                    identity_for_live_name,
                    sessions_table_ready,
                )

                if sessions_table_ready(conn):
                    row = identity_for_live_name(
                        conn, socket=socket_name, name=name
                    )
                    if row is not None and row.get("agent_type"):
                        usable = restart_agent_type(
                            str(row["agent_type"]),
                            row.get("agent_family_source"),
                        )
                        if usable:
                            return usable
            except sqlite3.Error as exc:
                logger.debug(
                    "restart_preview_agent_type_read_failed",
                    name=name,
                    error=str(exc),
                )
            finally:
                try:
                    conn.close()
                except sqlite3.Error:  # noqa: BLE001
                    pass
        for session in self._registry.sessions.values():
            if getattr(session, "tmux_session", None) == name and not self._is_remote_sid(session.id):
                return getattr(session, "agent_type", None)
        return None

    def _model_for_tmux_name(self, name: str) -> Optional[str]:
        for session in self._registry.sessions.values():
            if getattr(session, "tmux_session", None) == name and not self._is_remote_sid(session.id):
                return getattr(session, "model", None)
        return None

    def _persist_respawn_agent_type(
        self, *, name: str, socket_name: str, agent_type: str
    ) -> bool:
        """Write the picked wrapper onto this session's row.

        Description: the ONLY database write on the respawn path, and it
            is best effort by design. The restart has already happened
            and is visible to the user; a datastore that cannot be opened
            must not turn that into an error, so this reports False and
            the response says the choice was not remembered rather than
            claiming a restart failed that plainly did not.

        Inputs:
            name: literal tmux session name.
            socket_name: tmux socket the session lives on.
            agent_type: validated wrapper id.

        Output:
            bool: True when a row was updated.

        Example:
            >>> mgr._persist_respawn_agent_type(name="cloude_api",
            ...     socket_name="cloude", agent_type="claude-chrome")
            True
        """
        conn = self._writable_datastore_connection()
        if conn is None:
            logger.warning(
                "respawn_agent_type_not_persisted_no_datastore",
                name=name,
                agent_type=agent_type,
            )
            return False
        try:
            from src.core.session_agent_choice import persist_agent_type

            return persist_agent_type(
                conn, socket=socket_name, tmux_name=name, agent_type=agent_type
            )
        except sqlite3.Error as exc:
            logger.warning(
                "respawn_agent_type_persist_failed",
                name=name,
                agent_type=agent_type,
                error=str(exc),
            )
            return False
        finally:
            try:
                conn.close()
            except sqlite3.Error:  # noqa: BLE001
                pass

    def _row_identity_for_tmux_name(
        self, name: str, socket_name: str
    ) -> dict:
        out = {"session_id": None, "session_uuid": None}
        for sid, session in self._registry.sessions.items():
            if getattr(session, "tmux_session", None) == name and not self._is_remote_sid(sid):
                out["session_id"] = sid
                break
        conn = self._datastore_connection()
        if conn is None:
            return out
        try:
            from src.core.session_store import (
                identity_for_live_name,
                sessions_table_ready,
            )

            if not sessions_table_ready(conn):
                return out
            identity = identity_for_live_name(
                conn, socket=socket_name, name=name
            )
            if identity is None:
                return out
            row = conn.execute(
                "SELECT session_uuid FROM sessions WHERE id = ?",
                (int(identity["id"]),),
            ).fetchone()
            if row is not None:
                out["session_uuid"] = row["session_uuid"]
            return out
        except sqlite3.Error as exc:
            logger.debug("respawn_identity_read_failed", name=name, error=str(exc))
            return out
        finally:
            try:
                conn.close()
            except sqlite3.Error:  # noqa: BLE001
                pass

    async def _resolve_external_cwd(self, name: str) -> Path:
        from src.core.tmux_backend import _safe_target, DEFAULT_SOCKET_NAME, tmux_argv_prefix

        if parse_remote_session_id(name) is not None:
            return await remote_sessions.resolve_external_cwd(self, name)

        try:
            socket_name = settings.load_auth_config().session.tmux_socket_name
        except Exception:
            socket_name = DEFAULT_SOCKET_NAME

        try:
            target = _safe_target(name)
        except ValueError as exc:
            logger.warning(
                "adopt_cwd_unsafe_target", name=name, error=str(exc)
            )
            return Path.home()

        try:
            proc = await asyncio.create_subprocess_exec(
                *tmux_argv_prefix(socket_name), "display-message",
                "-t", target, "-p", "#{pane_current_path}",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                return Path.home()
            raw = out.decode("utf-8", errors="replace").strip()
            if not raw:
                return Path.home()
            path = Path(raw)
            return path if path.exists() else Path.home()
        except Exception as exc:
            logger.debug("adopt_cwd_probe_failed", name=name, error=str(exc))
            return Path.home()

    def consume_adopt_fifo_offset(
        self, session_id: Optional[str] = None
    ) -> Optional[int]:
        sid = self._registry.resolve_session_id(session_id)
        if not sid:
            return None
        return self._sidecars.take_fifo_offset(sid)
