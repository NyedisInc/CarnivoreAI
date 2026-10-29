
from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path
from typing import Any, Optional

import pytest

import os
import sys
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import session_manager as session_manager_module
from src.core.live_install_roots import LiveInstallRoots
from src.core.live_ports import (
    LiveSessionRecordStore,
    LiveSettings,
    SystemClock,
)
from src.core.sessions.ports import (
    Clock,
    InstallRoots,
    SessionRecordStore,
    SettingsReader,
    Target,
    TmuxReader,
)
from src.core.tmux_backend import TmuxBackend


def _protocol_members(protocol: type) -> list[str]:
    return sorted(getattr(protocol, "__protocol_attrs__", set()))


def _assert_signatures_match(protocol: type, implementation: Any) -> None:
    for name in _protocol_members(protocol):
        assert hasattr(implementation, name), f"{implementation} has no {name}"
        declared = inspect.signature(getattr(protocol, name))
        actual = inspect.signature(getattr(implementation, name))

        def _params(sig: inspect.Signature) -> list[tuple[str, Any]]:
            return [
                (p.name, p.kind)
                for p in sig.parameters.values()
                if p.name != "self"
            ]

        assert _params(actual) == _params(declared), (
            f"{implementation}.{name} takes {_params(actual)} but the "
            f"protocol declares {_params(declared)}"
        )




class FrozenClock:

    def __init__(self, *, at: float) -> None:
        self._at = at

    def now(self) -> float:
        return self._at

    def monotonic(self) -> float:
        return self._at


@pytest.mark.parametrize(
    "clock", [SystemClock(), FrozenClock(at=1_700_000_000.0)],
    ids=["real", "double"],
)
def test_clock_conforms(clock: Clock):
    assert isinstance(clock, Clock)
    _assert_signatures_match(Clock, clock)
    assert isinstance(clock.now(), float)
    assert isinstance(clock.monotonic(), float)


def test_the_real_clock_actually_moves_and_the_double_does_not():
    real = SystemClock()
    frozen = FrozenClock(at=1.0)

    assert real.monotonic() <= real.monotonic()
    assert frozen.monotonic() == frozen.monotonic() == 1.0


def test_an_object_missing_a_member_is_not_a_clock():

    class HalfClock:
        def now(self) -> float:
            return 0.0

    assert not isinstance(HalfClock(), Clock)




class StubSettingsReader:

    def __init__(self, *, pins: Path, cap: int, state: Path) -> None:
        self._pins, self._cap, self._state = pins, cap, state

    def pinned_themes_path(self) -> Path:
        return self._pins

    def log_buffer_size(self) -> int:
        return self._cap

    def state_dir(self) -> Path:
        return self._state

    def session_metadata_path(self) -> Path:
        return self._state / "session_metadata.json"


def test_settings_reader_conforms_real(tmp_path):
    reader = LiveSettings()

    assert isinstance(reader, SettingsReader)
    _assert_signatures_match(SettingsReader, reader)
    assert isinstance(reader.pinned_themes_path(), Path)
    assert isinstance(reader.log_buffer_size(), int)
    assert isinstance(reader.state_dir(), Path)
    assert isinstance(reader.session_metadata_path(), Path)


def test_settings_reader_conforms_double(tmp_path):
    reader = StubSettingsReader(pins=tmp_path / "p.json", cap=7, state=tmp_path)

    assert isinstance(reader, SettingsReader)
    _assert_signatures_match(SettingsReader, reader)
    assert reader.log_buffer_size() == 7


def test_the_live_reader_follows_the_patched_name_and_not_src_config(
    tmp_path, monkeypatch
):

    class _Stub:
        def get_pinned_themes_path(self) -> Path:
            return tmp_path / "patched.json"

    monkeypatch.setattr(session_manager_module, "settings", _Stub())

    assert LiveSettings().pinned_themes_path() == tmp_path / "patched.json"




class StubRecordStore:

    def __init__(self, *, row: Optional[dict] = None) -> None:
        self._row = row

    def read_connection(self) -> Optional[sqlite3.Connection]:
        return None

    def write_connection(self) -> Optional[sqlite3.Connection]:
        return None

    def get_instance(
        self, *, socket: str, name: str, epoch: Optional[int]
    ) -> Optional[dict]:
        return self._row


@pytest.mark.parametrize("store_kind", ["real", "double"])
def test_record_store_conforms(store_kind: str, tmp_path):
    if store_kind == "real":
        store: SessionRecordStore = LiveSessionRecordStore(
            settings_reader=StubSettingsReader(
                pins=tmp_path / "p.json", cap=1, state=tmp_path / "empty"
            )
        )
    else:
        store = StubRecordStore()

    assert isinstance(store, SessionRecordStore)
    _assert_signatures_match(SessionRecordStore, store)
    assert store.read_connection() is None
    assert store.write_connection() is None
    assert store.get_instance(socket="cloude", name="cloude_x", epoch=1) is None


def test_the_real_store_never_creates_the_database(tmp_path):
    state = tmp_path / "no_db_here"
    state.mkdir()
    store = LiveSessionRecordStore(
        settings_reader=StubSettingsReader(pins=tmp_path / "p.json", cap=1, state=state)
    )

    assert store.read_connection() is None
    assert store.write_connection() is None
    assert list(state.iterdir()) == [], "the store created a file it must not"


def test_the_real_store_opens_a_database_that_does_exist(tmp_path):
    from src.core.db import connect, db_path_for

    state = tmp_path / "with_db"
    state.mkdir()
    created = connect(db_path_for(state), create=True)
    created.close()

    store = LiveSessionRecordStore(
        settings_reader=StubSettingsReader(pins=tmp_path / "p.json", cap=1, state=state)
    )
    conn = store.read_connection()
    try:
        assert conn is not None, "an existing datastore was reported as absent"
    finally:
        if conn is not None:
            conn.close()




class StubTmuxReader:

    def is_alive(self) -> bool:
        return True

    def discover_existing(self) -> Any:
        return None

    def list_pane_status_all(self, *, fresh: bool = False) -> Any:
        return None

    def capture_scrollback(self, lines: int = 3000) -> bytes:
        return b""

    def capture_visible_screen(self) -> bytes:
        return b""


def test_the_real_tmux_backend_satisfies_the_reader_port(tmp_path, tmux_test_socket):
    backend = TmuxBackend(
        session_id="ses_conformance",
        working_dir=tmp_path,
        socket_name=tmux_test_socket,
    )

    assert isinstance(backend, TmuxReader)
    _assert_signatures_match(TmuxReader, backend)


def test_the_double_satisfies_the_reader_port():
    reader = StubTmuxReader()

    assert isinstance(reader, TmuxReader)
    _assert_signatures_match(TmuxReader, reader)


def test_a_reader_missing_one_method_is_refused():

    class NotAReader:
        def is_alive(self) -> bool:
            return True

    assert not isinstance(NotAReader(), TmuxReader)




class StubInstallRoots:

    def __init__(self, base: Path) -> None:
        self._base = base

    def targets_for(
        self, kind: str, scope: str, project_path: Optional[str]
    ) -> tuple:
        root = self._base if scope == "global" else Path(project_path or self._base)
        return (
            Target(harness="claude", leaf_dir=root / ".claude" / "skills"),
            Target(harness="codex", leaf_dir=root / ".codex" / "skills"),
        )

    def required_manifest(self, kind: str) -> str:
        from src.core.skills import kinds

        return kinds.manifest_name(kind)

    def trash_dir(
        self, harness: str, scope: str, project_path: str | None
    ) -> Path:
        return self._base / f".{harness}" / ".carnivore-trash"

    def staging_dir(self) -> Path:
        return self._base / "state" / "skills" / ".staging"

    def pending_dir(self) -> Path:
        return self._base / "state" / "skills" / ".pending"

    def root_listing(self, harness: str) -> tuple:
        root = self._base / f".{harness}" / "skills"
        if not root.is_dir():
            return ()
        return tuple(sorted(p.name for p in root.iterdir()))

    def present_harnesses(self) -> tuple:
        return ("claude", "codex")

    def legacy_targets_for(self, kind: str, scope: str, project_path) -> tuple:
        return ()

    def read_only_listing(self, harness: str) -> tuple:
        if harness != "codex":
            return ()
        root = self._base / ".agents" / "skills"
        if not root.is_dir():
            return ()
        return tuple(sorted(p.name for p in root.iterdir()))


@pytest.mark.parametrize("roots_kind", ["real", "double"])
def test_install_roots_conforms(roots_kind: str, tmp_path):
    if roots_kind == "real":
        roots: InstallRoots = LiveInstallRoots(
            settings_reader=StubSettingsReader(
                pins=tmp_path / "p.json", cap=1, state=tmp_path
            )
        )
    else:
        roots = StubInstallRoots(tmp_path)

    assert isinstance(roots, InstallRoots)
    _assert_signatures_match(InstallRoots, roots)


def test_the_real_install_roots_answers_the_state_dir_paths(tmp_path):
    roots = LiveInstallRoots(
        settings_reader=StubSettingsReader(
            pins=tmp_path / "p.json", cap=1, state=tmp_path / "state"
        )
    )

    assert roots.staging_dir() == tmp_path / "state" / "skills" / ".staging"
    assert roots.pending_dir() == tmp_path / "state" / "skills" / ".pending"


def test_install_roots_missing_one_method_is_refused():

    class HalfRoots:
        def staging_dir(self) -> Path:
            return Path("/tmp")

    assert not isinstance(HalfRoots(), InstallRoots)
