from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.session_manager import SessionManager
from src.core.sessions import wrapper_source

ROOT = Path(__file__).resolve().parents[3]


class _Source:

    def __init__(self, wrappers: list) -> None:
        self._wrappers = wrappers

    def load_auth_config(self) -> SimpleNamespace:
        return SimpleNamespace(agents=SimpleNamespace(wrappers=self._wrappers))


class _Broken:

    def __init__(self, error: Exception) -> None:
        self._error = error

    def load_auth_config(self) -> None:
        raise self._error


def test_the_injected_provider_decides_what_is_read() -> None:
    got = wrapper_source.configured_wrappers(settings_provider=lambda: _Source(["a", "b"]))
    assert got == ["a", "b"]


def test_no_wrappers_configured_is_an_empty_list() -> None:
    assert wrapper_source.configured_wrappers(settings_provider=lambda: _Source(None)) == []


@pytest.mark.parametrize("error", [FileNotFoundError("no config"), ValueError("bad json")])
def test_an_unreadable_config_degrades_to_empty(error: Exception) -> None:
    assert wrapper_source.configured_wrappers(settings_provider=lambda: _Broken(error)) == []


def test_a_wrong_attribute_path_is_not_swallowed() -> None:
    class _NoAgents:
        def load_auth_config(self) -> SimpleNamespace:
            return SimpleNamespace()

    with pytest.raises(AttributeError):
        wrapper_source.configured_wrappers(settings_provider=lambda: _NoAgents())


def test_the_config_reader_passes_the_process_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import settings, wrapper_reader

    seen: list = []
    monkeypatch.setattr(
        wrapper_source, "configured_wrappers",
        lambda *, settings_provider: seen.append(settings_provider()) or ["d"],
    )
    assert wrapper_reader.configured_wrappers() == ["d"]
    assert seen == [settings]


def test_the_manager_default_follows_its_own_settings_global(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.core.session_manager as sm

    manager = SessionManager()
    monkeypatch.setattr(sm, "settings", _Source(["w1"]))
    assert manager._wrappers_reader() == ["w1"]


def test_the_manager_takes_an_injected_reader() -> None:
    assert SessionManager(wrappers_reader=lambda: ["x"])._wrappers_reader() == ["x"]


def test_the_seam_module_imports_nothing_from_session_manager() -> None:
    tree = ast.parse((ROOT / "src/core/sessions/wrapper_source.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "session_manager" not in (node.module or "")
        elif isinstance(node, ast.Import):
            assert all("session_manager" not in a.name for a in node.names)


def test_no_module_imports_the_old_private_reader() -> None:
    import src.core.session_manager as sm

    assert not hasattr(sm, "_configured_wrappers")
