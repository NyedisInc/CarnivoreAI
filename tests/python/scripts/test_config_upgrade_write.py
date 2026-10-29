
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scripts import config_upgrade


def _run(tmp_path: Path, *extra: str) -> int:
    defaults = tmp_path / "defaults.json"
    defaults.write_text(json.dumps({"alpha": 1, "beta": 2}))
    return config_upgrade.main(
        ["--config", str(tmp_path / "config.json"), "--defaults", str(defaults), "--state-dir", str(tmp_path / "state"), "--apply", *extra]
    )


def test_apply_creates_a_private_config_and_an_atomic_base(tmp_path: Path) -> None:
    _run(tmp_path)
    config = tmp_path / "config.json"
    assert json.loads(config.read_text())["alpha"] == 1
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert json.loads((tmp_path / "state" / "config-base.json").read_text())["beta"] == 2
    assert not list((tmp_path / "state").glob("*.tmp"))


def test_apply_over_an_existing_config_leaves_a_dot_bak(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"alpha": 9}))
    _run(tmp_path)
    assert (tmp_path / "config.json.bak").exists()
    assert json.loads((tmp_path / "config.json").read_text())["alpha"] == 9


def test_an_unwritable_destination_is_exit_1_not_a_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(config_upgrade, "write_config", _boom)
    assert _run(tmp_path) == 1


def test_the_script_has_no_raw_config_write() -> None:
    source = Path(config_upgrade.__file__).read_text()
    assert "config_path.write_text" not in source
