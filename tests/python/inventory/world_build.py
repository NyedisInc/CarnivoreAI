
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.core.inventory.locations import Locations
from tests.python.inventory import world, world_files, world_main, world_side


def build_world(tmp_path: Path) -> SimpleNamespace:
    w = world.build_state(tmp_path)
    world.seed_sessions(w)
    world_main.seed_conversations(w)
    world_main.seed_graph(w)
    world_main.seed_swarm(w)
    world_main.seed_project(w)
    world_side.seed_task_manager(w)
    world_side.seed_small_stores(w)
    world_files.seed_claude_and_codex(w)
    world_files.seed_state_folder_files(w)
    world_files.seed_json_stores(w)
    w.locations = Locations(state_dir=w.state, config_path=w.config, homes=(w.home,), codex=w.codex)
    return w
