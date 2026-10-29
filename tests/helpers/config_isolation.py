
from __future__ import annotations

import shutil
from pathlib import Path

EXAMPLE_CONFIG = Path(__file__).resolve().parents[2] / "config.example.json"

TEST_CONFIG_NAME = "config.json"


class ConfigIsolationError(RuntimeError):
    pass


def build_test_config(directory: Path) -> Path:
    if not EXAMPLE_CONFIG.is_file():
        raise ConfigIsolationError(f"config template not found: {EXAMPLE_CONFIG}")
    target = directory / TEST_CONFIG_NAME
    shutil.copyfile(EXAMPLE_CONFIG, target)
    return target


def assert_under_temp(path: Path, temp_root: Path) -> None:
    resolved, root = path.expanduser().resolve(), temp_root.resolve()
    if root not in resolved.parents:
        raise ConfigIsolationError(f"test config {resolved} is outside the pytest temp root {root}")
