
from __future__ import annotations

from src.core.boot import (
    agy_boot, app_wiring, attention, auth_stores, background, config_chain, core, federation, first_run, mods_boot, notifications, plugins,
    schedulers,
)
from src.core.boot.steps import BootRegistry


def build_registry() -> BootRegistry:
    modules = (config_chain, core, first_run, notifications, auth_stores, app_wiring, background, attention, schedulers,
               federation, plugins, mods_boot, agy_boot)
    return BootRegistry([step for module in modules for step in module.steps()])
