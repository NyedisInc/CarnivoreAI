
from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.config_isolation import ConfigIsolationError, assert_under_temp, build_test_config


def test_a_path_outside_the_temp_root_is_refused(tmp_path: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    with pytest.raises(ConfigIsolationError):
        assert_under_temp(Path(__file__).resolve().parents[1] / "config.json", tmp_path_factory.getbasetemp())


def test_a_built_copy_is_inside_the_temp_root(tmp_path: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    assert_under_temp(build_test_config(tmp_path), tmp_path_factory.getbasetemp())
