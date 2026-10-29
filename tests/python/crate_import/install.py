
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from src.core.conversation_writers import Writer
from src.core.crate_import.env import ImportEnv
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.project_move.plan import PaneListing
from src.core.work.storage import storage_for

INSTALL_ID = "11111111-1111-4111-8111-111111111111"


@dataclass
class Install:

    env: ImportEnv
    state: Path
    projects: Path
    claude: Path
    codex: Path

    def db(self):  # noqa: ANN201
        return connect(db_path_for(self.state))


def make_install(tmp: Path, *, panes: Optional[PaneListing] = None, writers: Optional[Tuple[Writer, ...]] = (),
                 install_id: Optional[str] = INSTALL_ID) -> Install:
    state, projects = tmp / "state", tmp / "projects"
    claude, codex = tmp / "claude", tmp / "codex"
    for folder in (state, projects, claude / "projects", codex):
        folder.mkdir(parents=True, exist_ok=True)
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    storage_for(state).connect(True).close()
    env = ImportEnv(state=state, projects_dir=str(projects), claude_homes=(claude,), codex_home=codex, install_id=install_id,
                    panes=lambda: panes or PaneListing(True), writers=lambda: writers, free_bytes=lambda path: 10**12)
    return Install(env, state, projects, claude, codex)
