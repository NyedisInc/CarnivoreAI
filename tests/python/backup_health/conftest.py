
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_real_env_file(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    missing: Path = tmp_path_factory.mktemp("noenv") / ".env"
    monkeypatch.setattr("src.api.enrollment_routes.env_file_path", lambda: missing)
