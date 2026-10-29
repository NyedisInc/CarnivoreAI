
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.core.catalog.services import CatalogServices, build_catalog_services
from src.core.live_install_roots import LiveInstallRoots
from src.core.live_ports import (
    LiveSessionRecordStore,
    LiveSettings,
    SystemClock,
)
from src.core.session_manager import SessionManager
from src.core.sessions.ports import (
    Clock,
    InstallRoots,
    SessionRecordStore,
    SettingsReader,
)
from src.core.sessions.owned_tmux_ledger import OwnedTmuxLedger
from src.core.sessions.probe_health import ProbeHealthRecorder
from src.core.sessions.registry import SessionRegistry
from src.core.sessions.sidecars import AttachmentSidecars
from src.core.sessions import theme_global
from src.core.sessions.theme_store import ThemeStore
from src.core.sessions.toast_inbox import ToastInbox
from src.core.ui_preferences_store import UiPreferencesStore


@dataclass(frozen=True)
class AppServices:

    session_manager: SessionManager

    probe_health: ProbeHealthRecorder
    themes: ThemeStore
    toasts: ToastInbox
    registry: SessionRegistry
    sidecars: AttachmentSidecars
    owned_tmux: OwnedTmuxLedger

    clock: Clock
    settings_reader: SettingsReader
    records: SessionRecordStore
    install_roots: InstallRoots

    catalog: CatalogServices

    ui_preferences: Optional[UiPreferencesStore] = None


def _live_index_url() -> str:
    from src.core import session_manager

    return session_manager.settings.get_catalog_index_url()


def _live_api_base_url() -> str:
    from src.core import session_manager

    return session_manager.settings.get_catalog_api_base_url()


def _live_db_factory(
    settings_reader: SettingsReader,
) -> Callable[[], sqlite3.Connection]:
    from src.core.db import connect, db_path_for

    def open_db() -> sqlite3.Connection:
        return connect(db_path_for(Path(settings_reader.state_dir())))

    return open_db


def build_services(
    *,
    settings_reader: Optional[SettingsReader] = None,
    clock: Optional[Clock] = None,
    records: Optional[SessionRecordStore] = None,
    install_roots: Optional[InstallRoots] = None,
    catalog: Optional[CatalogServices] = None,
    probe_health: Optional[ProbeHealthRecorder] = None,
    themes: Optional[ThemeStore] = None,
    toasts: Optional[ToastInbox] = None,
    registry: Optional[SessionRegistry] = None,
    sidecars: Optional[AttachmentSidecars] = None,
    owned_tmux: Optional[OwnedTmuxLedger] = None,
    session_manager: Optional[SessionManager] = None,
    ui_preferences: Optional[UiPreferencesStore] = None,
) -> AppServices:
    collaborator_args = {
        "probe_health": probe_health,
        "themes": themes,
        "toasts": toasts,
        "registry": registry,
        "sidecars": sidecars,
        "owned_tmux": owned_tmux,
    }
    if session_manager is not None:
        conflicting = sorted(k for k, v in collaborator_args.items() if v is not None)
        if conflicting:
            raise ValueError(
                "build_services got session_manager together with "
                f"{conflicting}; a manager already owns its collaborators, so "
                "honouring both would create two objects holding one state"
            )

    resolved_settings: SettingsReader = (
        settings_reader if settings_reader is not None else LiveSettings()
    )
    resolved_clock: Clock = clock if clock is not None else SystemClock()
    resolved_records: SessionRecordStore = (
        records
        if records is not None
        else LiveSessionRecordStore(settings_reader=resolved_settings)
    )
    resolved_install_roots: InstallRoots = (
        install_roots
        if install_roots is not None
        else LiveInstallRoots(settings_reader=resolved_settings)
    )

    resolved_catalog: CatalogServices = (
        catalog
        if catalog is not None
        else build_catalog_services(
            index_url=_live_index_url,
            api_base_url=_live_api_base_url,
            clock=resolved_clock,
            open_db=_live_db_factory(resolved_settings),
        )
    )

    if session_manager is not None:
        manager = session_manager
        resolved_probe = manager._probe_health
        resolved_themes = manager._theme_store
        resolved_toasts = manager._toast_inbox
        resolved_registry = manager._registry
        resolved_sidecars = manager._sidecars
        resolved_owned = manager._owned
    else:
        resolved_probe = (
            probe_health if probe_health is not None else ProbeHealthRecorder()
        )
        resolved_themes = (
            themes
            if themes is not None
            else ThemeStore(
                pin_path=resolved_settings.pinned_themes_path,
                global_theme=(
                    theme_global.theme_reader_over_block(ui_preferences.read)
                    if ui_preferences is not None
                    else None
                ),
            )
        )
        resolved_toasts = toasts if toasts is not None else ToastInbox()
        resolved_registry = (
            registry
            if registry is not None
            else SessionRegistry(log_cap=resolved_settings.log_buffer_size)
        )
        resolved_sidecars = (
            sidecars if sidecars is not None else AttachmentSidecars()
        )
        resolved_owned = (
            owned_tmux
            if owned_tmux is not None
            else OwnedTmuxLedger(
                metadata_path=resolved_settings.session_metadata_path,
                records=resolved_records,
                socket_name=lambda: manager.tmux_socket_name(),
            )
        )
        manager = SessionManager(
            probe_health=resolved_probe,
            theme_store=resolved_themes,
            toast_inbox=resolved_toasts,
            registry=resolved_registry,
            sidecars=resolved_sidecars,
            owned_tmux=resolved_owned,
        )

    return AppServices(
        session_manager=manager,
        probe_health=resolved_probe,
        themes=resolved_themes,
        toasts=resolved_toasts,
        registry=resolved_registry,
        sidecars=resolved_sidecars,
        owned_tmux=resolved_owned,
        clock=resolved_clock,
        settings_reader=resolved_settings,
        records=resolved_records,
        install_roots=resolved_install_roots,
        catalog=resolved_catalog,
        ui_preferences=ui_preferences,
    )
