
from pathlib import Path

import pytest

from scripts.warez.hold import STATE_ENV


@pytest.fixture(autouse=True)
def isolated_runner_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "warez-runner-state"
    monkeypatch.setenv(STATE_ENV, str(folder))
    return folder
