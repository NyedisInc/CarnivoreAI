import json
import sqlite3
import threading
from pathlib import Path

from src.core.unread_store import UnreadStore, live_session_row_ids


def test_corrupt_file_starts_empty_without_raising(tmp_path: Path) -> None:
    path = tmp_path / "unread.json"
    path.write_text("{not json")
    assert UnreadStore(path).raw == {}


def test_unexpected_error_in_load_is_not_swallowed(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "unread.json"
    path.write_text("{}")
    monkeypatch.setattr(json, "load", lambda f: (_ for _ in ()).throw(AttributeError("bug")))
    try:
        UnreadStore(path)
    except AttributeError:
        return
    raise AssertionError("AttributeError was swallowed")


def test_concurrent_set_flag_and_save_lose_nothing(tmp_path: Path) -> None:
    path = tmp_path / "unread.json"
    store = UnreadStore(path)
    errors: list[BaseException] = []

    def writer(base: int) -> None:
        try:
            for i in range(200):
                store.set_flag(f"cloude_w{base}_{i}", "auto", True, epoch=1)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len(json.loads(path.read_text())) == 800


def test_prune_drops_row_keys_whose_row_is_gone(tmp_path: Path) -> None:
    store = UnreadStore(tmp_path / "unread.json")
    store.set_follow_up(4, None)
    store.set_follow_up(9, None)
    store.prune(set(), live_row_ids={4})
    assert set(store.raw) == {"row:4"}


def test_prune_keeps_row_keys_when_the_datastore_is_unreadable(tmp_path: Path) -> None:
    store = UnreadStore(tmp_path / "unread.json")
    store.set_follow_up(9, None)
    store.prune(set(), live_row_ids=None)
    assert set(store.raw) == {"row:9"}


def test_live_row_ids_reads_sessions_and_degrades_to_none() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO sessions VALUES (?)", [(1,), (2,)])
    assert live_session_row_ids(lambda: conn) == {1, 2}
    assert live_session_row_ids(lambda: None) is None
    bare = sqlite3.connect(":memory:")
    assert live_session_row_ids(lambda: bare) is None


def test_stale_disk_read_never_overwrites_a_newer_commit(tmp_path: Path, monkeypatch) -> None:
    from src.core.ui_preferences_store import UiPreferencesStore

    config_path = tmp_path / "config.json"
    config_path.write_text("{}")
    store = UiPreferencesStore(lambda: config_path)
    newer = {"revision": 7, "values": {}, "schema_version": 1}
    real_load = store._load_from_disk

    def racing_load(path: Path) -> dict:
        old = real_load(path)
        monkeypatch.setattr("src.core.ui_preferences_store.ui_preferences.read_block", lambda data: newer)
        store._observe_commit(path, {})
        return old

    monkeypatch.setattr(store, "_load_from_disk", racing_load)
    store.read()
    assert store.read()["revision"] == 7
