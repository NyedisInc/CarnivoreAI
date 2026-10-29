
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from src.core.crate_import import hooks as apply_hooks  # noqa: F401
from src.core.crate_import import ledger  # noqa: F401
from src.core.crate_import.apply import (  # noqa: F401
    ImportReceipt,
    apply_import,
    finish_import,
    recover_files,
)
from src.core.crate_import.backups_folder_in import unit_ok as backup_unit_ok  # noqa: F401
from src.core.crate_import.env import EnvUnreadable, ImportEnv, StoreHome  # noqa: F401
from src.core.crate_import.hooks import ApplyHooks  # noqa: F401
from src.core.crate_import.model import (  # noqa: F401
    B_CRATE_NOT_FOUND,
    B_NEEDS_IDENTITY,
    B_TOO_NEW,
    B_VERIFY_FAILED,
    BLOCKER_CODES,
    MODES,
    IMPORT_ID_RE,
    WARNING_CODES,
    ImportFailed,
    ImportRefused,
    ImportRequest,
    new_import_id,
)
from src.core.crate_import.plan import build_plan as plan_import  # noqa: F401
from src.core.crate_import.undo import log_counts as undo_log_counts  # noqa: F401
from src.core.crate_import.undo_import import (  # noqa: F401
    UndoPlan,
    UndoReport,
    UndoRefused,
    plan_undo,
    run_undo,
)
from src.core.inventory.locations import Locations
from src.core.project_move.plan import PaneListing


def plugin_homes_of(locations: Locations) -> Callable[[str, str], Optional[StoreHome]]:
    from src.core.inventory import plugin_stores as ps

    def home(plugin_id: str, data_id: str) -> Optional[StoreHome]:
        for store in ps.declared_stores(locations):
            if store.plugin_id == plugin_id and store.decl.id == data_id:
                if store.location is None or ps.root_problem(store, locations) is not None:
                    return None
                return StoreHome(root=Path(store.location), purge=store.decl.policy.purge, default=store.defaulted)
        return None

    return home


def plugin_enabled_of(locations: Locations) -> Callable[[str], bool]:
    from src.core.inventory import plugin_stores as ps

    def enabled(plugin_id: str) -> bool:
        return any(m.id == plugin_id and ps.enabled_of(locations, m) for m in ps.manifests_of(locations))

    return enabled


RELINK_PORT = "reviewboard.relink"


def relink_board_of() -> Callable[[str, int], bool]:
    from src.cplugs.sdk import ports

    def relink(slug: str, item_id: int) -> bool:
        port = ports.get(RELINK_PORT)
        return bool(port.relink(slug, item_id)) if port is not None else False

    return relink


def import_env(state: Path, locations: Locations, install_id: Optional[str], live_panes: Callable[[], PaneListing]) -> ImportEnv:
    from src.config import settings
    from src.core.project_directory import projects_root

    return ImportEnv(state=Path(state), projects_dir=projects_root(settings), claude_homes=tuple(locations.claude_homes()),
                     codex_home=Path(locations.codex_home()), install_id=install_id, panes=live_panes,
                     receipts=Path(state) / "cplugs" / "crate" / "imports",
                     config_path=Path(settings.auth_config_file).expanduser(), plugin_homes=plugin_homes_of(locations),
                     plugin_enabled=plugin_enabled_of(locations), relink_board=relink_board_of())


__all__ = ["ApplyHooks", "BLOCKER_CODES", "B_CRATE_NOT_FOUND", "B_NEEDS_IDENTITY", "B_TOO_NEW", "B_VERIFY_FAILED", "EnvUnreadable",
           "IMPORT_ID_RE", "ImportEnv", "ImportFailed", "ImportReceipt", "ImportRefused", "ImportRequest", "MODES", "StoreHome", "WARNING_CODES",
           "apply_hooks", "apply_import", "backup_unit_ok", "finish_import", "RELINK_PORT", "import_env", "ledger", "new_import_id", "plan_import", "plugin_enabled_of", "plugin_homes_of", "recover_files", "UndoPlan", "UndoReport", "UndoRefused", "plan_undo", "run_undo", "undo_log_counts"]
