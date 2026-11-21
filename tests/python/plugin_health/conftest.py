import pytest

from src.plugins.host import developer_mode


@pytest.fixture(autouse=True)
def developer_mode_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
