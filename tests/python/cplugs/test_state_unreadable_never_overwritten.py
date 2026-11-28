
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.plugins.host import registry_store, runtime, state as owner_state

GARBAGE = b'{"schema": 2, "generation": 1, "items": {"huddle": {"enabled": tru'
NOT_AN_OBJECT = b'["a", "list"]'
CPLUGS_NOT_AN_OBJECT = b'{"schema": 2, "generation": 1, "items": [], "tombstones": {}}'


def _manifest() -> object:
    found = runtime.find("taskmanager")
    assert found is not None
    return found.manifest


def _update(state_dir: Path) -> None:
    owner_state.update(state_dir, _manifest(), None, lambda st: replace(st, enabled=True))


WRITERS = {
    "update": _update,
    "strip_consent": lambda d: owner_state.strip_consent(d, "taskmanager"),
    "forget": lambda d: owner_state.forget(d, "taskmanager"),
}


@pytest.mark.parametrize("content", [GARBAGE, NOT_AN_OBJECT, CPLUGS_NOT_AN_OBJECT, b"\xff\xfe\x00bad utf8"])
@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_writer_refuses_an_unreadable_file(tmp_path: Path, writer: str, content: bytes) -> None:
    path = registry_store.registry_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    registry_store._cache.clear()
    with pytest.raises(owner_state.StateUnreadable):
        WRITERS[writer](tmp_path)
    assert path.read_bytes() == content


def test_unreadable_is_a_state_write_failed(tmp_path: Path) -> None:
    assert issubclass(owner_state.StateUnreadable, owner_state.StateWriteFailed)


def test_readers_still_default_when_unreadable(tmp_path: Path) -> None:
    path = registry_store.registry_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(GARBAGE)
    registry_store._cache.clear()
    assert owner_state.stored_ids(tmp_path) == ()
    assert owner_state.get(tmp_path, _manifest()).stored is False


def test_missing_file_is_still_writable(tmp_path: Path) -> None:
    _update(tmp_path)
    assert owner_state.stored_ids(tmp_path) == ("taskmanager",)


def test_other_plugins_survive_a_write(tmp_path: Path) -> None:
    owner_state.update(tmp_path, runtime.find("unread").manifest, None, lambda st: replace(st, enabled=True))
    _update(tmp_path)
    assert set(owner_state.stored_ids(tmp_path)) == {"taskmanager", "unread"}
