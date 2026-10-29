
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lotl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lotl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import listing_gather
from src.core.listing_prefetch import ListingPrefetch, build_listing_prefetch
from src.core.session_manager import SessionManager
from src.core.session_status_map import StatusMap
from src.models import Session, SessionStatus

TEST_SOCKET = "cloude_lotl_test"
PARK_TIMEOUT_SECONDS = 10.0
HEARTBEAT_SECONDS = 0.005
HEARTBEAT_MAX_TICKS = 400


class _FakeBackend:

    def __init__(
        self,
        session_id: str,
        tmux_session: str | None,
        alive: bool = True,
    ) -> None:
        self.session_id = session_id
        self.tmux_session = tmux_session
        self.socket_name = TEST_SOCKET
        self.pid = 4321
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


def _manager_with(sessions: list[tuple[str, str | None]]) -> SessionManager:
    manager = SessionManager()
    for session_id, tmux_name in sessions:
        manager._registry.backends[session_id] = _FakeBackend(session_id, tmux_name)
        manager._registry.sessions[session_id] = Session(
            id=session_id,
            status=SessionStatus.RUNNING,
            working_dir=str(ROOT),
            created_at=datetime.utcnow(),
        )
    return manager


def _status_rows(names: list[str], *, dead: set[str] | None = None) -> StatusMap:
    dead = dead or set()
    return StatusMap(
        {
            name: {
                "name": name,
                "pane_dead": "1" if name in dead else "0",
                "pane_current_command": "sleep",
                "pid": 4321,
                "status": "dead" if name in dead else "running",
                "created_at_epoch": 1700000000,
            }
            for name in names
        },
        complete=True,
        socket=TEST_SOCKET,
    )



def test_the_listing_gather_runs_off_the_event_loop(monkeypatch):
    manager = _manager_with([("ses_a", "cloude_a")])
    entered = threading.Event()
    released = threading.Event()

    def parked_status_map() -> StatusMap:
        entered.set()
        if not released.wait(timeout=PARK_TIMEOUT_SECONDS):
            raise AssertionError(
                "the event loop never got to run while the gather was in "
                "progress: the gather is ON the loop"
            )
        return _status_rows(["cloude_a"])

    monkeypatch.setattr(manager, "_build_tmux_status_map", parked_status_map)
    monkeypatch.setattr(
        manager, "_instance_index_for_listing", lambda **_kw: None
    )
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: None)
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: None)
    monkeypatch.setattr(manager._owned, "instances_from_db", lambda: set())

    async def scenario():
        task = asyncio.create_task(manager.list_session_infos())
        ticks = 0
        for _ in range(HEARTBEAT_MAX_TICKS):
            await asyncio.sleep(HEARTBEAT_SECONDS)
            ticks += 1
            if entered.is_set():
                released.set()
                break
        infos = await task
        return ticks, infos

    ticks, infos = asyncio.run(scenario())
    assert entered.is_set(), "the gather never started"
    assert ticks > 0, "the loop was starved for the whole gather"
    assert len(infos) == 1, "a cheaper pass that loses rows is not the fix"


def test_the_loop_test_can_detect_a_gather_that_is_on_the_loop():
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.001)
            ticks += 1

    async def scenario():
        nonlocal ticks
        beat = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.02)
        assert ticks > 0, "the heartbeat never started, so it proves nothing"
        before = ticks
        time.sleep(0.30)
        during = ticks - before
        beat.cancel()
        return during

    assert asyncio.run(scenario()) == 0, (
        "a synchronous 300ms call inside a coroutine let the loop run, so "
        "this harness cannot detect loop blocking and the test above is "
        "worthless"
    )



@pytest.mark.parametrize(
    "case,label,identity,restored,owned,dead",
    [
        ("a fully decorated row", "work", {"id": 7, "parent_session_id": None,
         "agent_type": "claude-chrome", "agent_family_source": "launched"},
         "idle", {("cloude_a", 1700000000)}, False),
        ("an unreadable row - every reader answers None", None, None, None,
         None, False),
        ("a row with no label but a real identity", None,
         {"id": 9, "parent_session_id": None, "agent_type": None,
          "agent_family_source": None}, None, set(), False),
        ("a dead pane", "work", None, None, set(), True),
    ],
)
def test_the_prefetched_row_is_identical_to_the_per_row_read(
    monkeypatch, case, label, identity, restored, owned, dead
):
    name = "cloude_a"
    manager = _manager_with([("ses_a", name)])
    monkeypatch.setattr(
        manager,
        "_build_tmux_status_map",
        lambda: _status_rows([name], dead={name} if dead else set()),
    )
    monkeypatch.setattr(
        manager, "_instance_index_for_listing", lambda **_kw: None
    )
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: label)
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: identity)
    monkeypatch.setattr(manager._owned, "instances_from_db", lambda: owned)

    prefetched = asyncio.run(manager.list_session_infos())

    per_row = manager._session_info_for(
        "ses_a",
        status_map=manager._build_tmux_status_map(),
        instance_index=None,
        prefetch=None,
    )

    if dead:
        assert prefetched == [] and per_row is None, (
            f"{case}: a dead pane must drop off the live list on both paths"
        )
        return
    assert len(prefetched) == 1 and per_row is not None, case
    assert prefetched[0].model_dump_json() == per_row.model_dump_json(), (
        f"{case}: the prefetched row is not byte-identical to the row the "
        "per-row readers produce"
    )


def test_an_adopted_id_is_decorated_the_same_way(monkeypatch):
    name = "cloude_adoptme"
    manager = _manager_with([(f"adopted:{name}", name)])
    monkeypatch.setattr(
        manager, "_build_tmux_status_map", lambda: _status_rows([name])
    )
    monkeypatch.setattr(
        manager, "_instance_index_for_listing", lambda **_kw: None
    )
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: "adopted")
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: None)
    monkeypatch.setattr(manager._owned, "instances_from_db", lambda: set())

    prefetched = asyncio.run(manager.list_session_infos())
    per_row = manager._session_info_for(
        f"adopted:{name}",
        status_map=manager._build_tmux_status_map(),
        instance_index=None,
        prefetch=None,
    )
    assert len(prefetched) == 1 and per_row is not None
    assert prefetched[0].model_dump_json() == per_row.model_dump_json()


def test_an_incomplete_listing_produces_the_same_row_on_both_paths(monkeypatch):
    name = "cloude_a"
    manager = _manager_with([("ses_a", name)])
    monkeypatch.setattr(manager, "_build_tmux_status_map", StatusMap)
    monkeypatch.setattr(
        manager, "_instance_index_for_listing", lambda **_kw: None
    )
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: "x")
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: None)
    monkeypatch.setattr(manager._owned, "instances_from_db", lambda: None)

    prefetched = asyncio.run(manager.list_session_infos())
    per_row = manager._session_info_for(
        "ses_a", status_map=StatusMap(), instance_index=None, prefetch=None
    )
    assert len(prefetched) == 1 and per_row is not None
    assert prefetched[0].model_dump_json() == per_row.model_dump_json()



def test_an_adoption_landing_during_the_gather_is_reported_owned(monkeypatch):
    manager = _manager_with([("ses_a", "cloude_a")])
    adopted: set[tuple[str, int]] = set()

    def entering_gather() -> StatusMap:
        adopted.add(("cloude_a", 1700000000))
        return _status_rows(["cloude_a"])

    monkeypatch.setattr(manager, "_build_tmux_status_map", entering_gather)
    monkeypatch.setattr(
        manager, "_instance_index_for_listing", lambda **_kw: None
    )
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: None)
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: None)
    monkeypatch.setattr(
        manager._owned, "instances_from_db", lambda: set(adopted)
    )

    infos = asyncio.run(manager.list_session_infos())
    assert [i.created_by_cloude for i in infos] == [True], (
        "an adoption that landed while the gather ran was reported unowned, "
        "so the ownership read is being answered from a frozen snapshot"
    )


def test_ownership_is_never_answered_from_the_prefetch():
    prefetch = build_listing_prefetch(
        names=["cloude_a"],
        label_for_name=lambda _n: None,
        identity_for_live_name=lambda _n: None,
    )
    fields = set(type(prefetch).__dataclass_fields__)
    assert fields == {"by_name"}, (
        f"the prefetch grew a field beyond the three name-keyed "
        f"decorations: {sorted(fields)}. If that field is the ownership "
        "read, it re-opens the window where an adoption landing during "
        "the gather is reported unowned for a poll cycle."
    )
    assert "owned_instances_from_db" not in (
        listing_gather.ListingReaders.__dataclass_fields__
    ), "the ownership read is back in the gather thread"


def test_a_session_registered_during_the_gather_falls_through_to_live_reads(
    monkeypatch,
):
    manager = _manager_with([("ses_a", "cloude_a")])
    live_reads: list[str] = []

    def entering_gather() -> StatusMap:
        manager._registry.backends["ses_b"] = _FakeBackend("ses_b", "cloude_b")
        manager._registry.sessions["ses_b"] = Session(
            id="ses_b",
            status=SessionStatus.RUNNING,
            working_dir=str(ROOT),
            created_at=datetime.utcnow(),
        )
        return _status_rows(["cloude_a", "cloude_b"])

    monkeypatch.setattr(manager, "_build_tmux_status_map", entering_gather)
    monkeypatch.setattr(
        manager, "_instance_index_for_listing", lambda **_kw: None
    )

    def label(name):
        live_reads.append(name)
        return f"label-{name}"

    monkeypatch.setattr(manager, "_label_for_tmux_name", label)
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: None)
    monkeypatch.setattr(manager._owned, "instances_from_db", lambda: set())

    infos = asyncio.run(manager.list_session_infos())
    labels = {i.tmux_session: i.label for i in infos}
    assert labels == {
        "cloude_a": "label-cloude_a",
        "cloude_b": "label-cloude_b",
    }, "the late session lost its decorations instead of reading them live"
    assert "cloude_b" in live_reads, (
        "the late session must reach the live reader, not a fabricated None"
    )



def test_names_are_deduplicated_and_falsy_names_are_skipped():
    seen: list[str] = []

    def label(name):
        seen.append(name)
        return name

    prefetch = build_listing_prefetch(
        names=["cloude_a", "cloude_a", None, "", "cloude_b"],
        label_for_name=label,
        identity_for_live_name=lambda _n: None,
    )
    assert seen == ["cloude_a", "cloude_b"]
    assert prefetch.has("cloude_a") and prefetch.has("cloude_b")
    assert not prefetch.has(None) and not prefetch.has("cloude_c")


def test_an_empty_prefetch_reports_every_name_absent():
    empty = ListingPrefetch()
    assert empty.has("cloude_a") is False
    assert empty.label_for("cloude_a") is None


def test_listing_does_not_reread_the_watchers_attention_evidence(monkeypatch):
    from src.core import listing_attention
    from src.core.attention import registry_index

    scans: list = []
    tails: list = []
    monkeypatch.setattr(registry_index, "read_registry_index", lambda: scans.append(1) or {})
    monkeypatch.setattr(listing_attention, "transcript_facts_for", lambda *args, **kw: tails.append(args))

    readers = listing_gather.ListingReaders(
        build_status_map=lambda: _status_rows(["cloude_a", "cloude_b"]),
        build_instance_index=lambda **kw: None,
        label_for_name=lambda n: None,
        identity_for_live_name=lambda _n: None,
    )
    snapshot = listing_gather.ListingSnapshot(
        socket=TEST_SOCKET,
        seed_candidate_names=("cloude_a", "cloude_b"),
        decorated_names=("cloude_a", "cloude_b"),
    )

    gathered = listing_gather.gather_listing_inputs(readers, snapshot)

    assert scans == []
    assert tails == []
    for name in ("cloude_a", "cloude_b"):
        assert gathered.prefetch.registry_for(name) is None
        assert gathered.prefetch.transcript_for(name) is None


def test_a_prefetch_built_without_the_attention_readers_reports_them_absent():
    prefetch = build_listing_prefetch(
        names=["cloude_a"],
        label_for_name=lambda n: n,
        identity_for_live_name=lambda _n: None,
    )
    assert prefetch.has("cloude_a") is True
    assert prefetch.registry_for("cloude_a") is None
    assert prefetch.transcript_for("cloude_a") is None


def test_the_gather_reaches_nothing_but_its_two_arguments():
    snapshot = listing_gather.ListingSnapshot(
        socket=TEST_SOCKET,
        seed_candidate_names=("cloude_a",),
        decorated_names=("cloude_a", "cloude_b"),
    )
    readers = listing_gather.ListingReaders(
        build_status_map=lambda: _status_rows(["cloude_a"]),
        build_instance_index=lambda **kw: kw,
        label_for_name=lambda n: f"L{n}",
        identity_for_live_name=lambda _n: None,
    )
    gathered = listing_gather.gather_listing_inputs(readers, snapshot)
    assert gathered.instance_index == {
        "socket": TEST_SOCKET,
        "names": ["cloude_a"],
    }, "the seed index must be built over the SEED candidates only"
    assert set(gathered.prefetch.by_name) == {"cloude_a", "cloude_b"}, (
        "the decorations must be built over every listed name, which is a "
        "wider set than the seed candidates"
    )
    assert gathered.elapsed_ms >= 0.0



LIVE_CONTAINERS = (
    ("_registry", "sessions"),
    ("_registry", "backends"),
    (None, "_instance_epochs"),
    ("_theme_store", "pinned_themes"),
    ("hook_tokens", "tmux_names"),
)


class _ThreadRecordingProxy:

    def __init__(self, wrapped: object, name: str, seen: dict) -> None:
        object.__setattr__(self, "_wrapped", wrapped)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_seen", seen)

    def _record(self) -> None:
        name = object.__getattribute__(self, "_name")
        seen = object.__getattribute__(self, "_seen")
        seen.setdefault(name, set()).add(threading.current_thread().name)

    def __getattr__(self, item):
        self._record()
        return getattr(object.__getattribute__(self, "_wrapped"), item)

    def __getitem__(self, key):
        self._record()
        return object.__getattribute__(self, "_wrapped")[key]

    def __setitem__(self, key, value) -> None:
        self._record()
        object.__getattribute__(self, "_wrapped")[key] = value

    def __contains__(self, key) -> bool:
        self._record()
        return key in object.__getattribute__(self, "_wrapped")

    def __iter__(self):
        self._record()
        return iter(object.__getattribute__(self, "_wrapped"))

    def __len__(self) -> int:
        self._record()
        return len(object.__getattribute__(self, "_wrapped"))


def _run_readers_in_a_thread(manager: SessionManager) -> dict:
    seen: dict = {}
    for owner_attr, name in LIVE_CONTAINERS:
        owner = manager if owner_attr is None else getattr(manager, owner_attr)
        label = name if owner_attr is None else f"{owner_attr}.{name}"
        setattr(
            owner,
            name,
            _ThreadRecordingProxy(getattr(owner, name), label, seen),
        )
    readers = manager._listing_readers()
    snapshot = listing_gather.ListingSnapshot(
        socket=TEST_SOCKET,
        seed_candidate_names=("cloude_a",),
        decorated_names=("cloude_a",),
    )

    async def drive() -> None:
        await asyncio.to_thread(
            listing_gather.gather_listing_inputs, readers, snapshot
        )

    asyncio.run(drive())
    return seen


def test_the_gather_thread_touches_no_live_shared_container():
    manager = _manager_with([("ses_a", "cloude_a")])
    main_thread = threading.current_thread().name
    seen = _run_readers_in_a_thread(manager)

    off_loop = {
        name: sorted(threads - {main_thread})
        for name, threads in seen.items()
        if threads - {main_thread}
    }
    assert not off_loop, (
        "a listing reader touched live shared state from the gather "
        f"thread: {off_loop}. The loop mutates every one of these from "
        "the hook route, the adopt path and the theme PATCH while the "
        "gather runs. Snapshot the value into ListingSnapshot on the "
        "loop instead of reading it here."
    )


def test_the_tripwire_can_detect_a_reader_that_reads_a_live_container():
    manager = _manager_with([("ses_a", "cloude_a")])
    main_thread = threading.current_thread().name

    def reads_live_state(_name):
        return str(len(manager._registry.sessions))

    manager._label_for_tmux_name = reads_live_state
    seen = _run_readers_in_a_thread(manager)

    assert any(
        threads - {main_thread} for threads in seen.values()
    ), (
        "the harness did not notice a reader reading self.sessions from "
        "the gather thread, so the tripwire beside it is vouching for "
        "nothing"
    )


@pytest.mark.parametrize(
    "state,reason,expected",
    [
        ("busy", "streaming", "working"),
        ("needs_user", "permission", "question"),
        ("done_idle", "turn_ended", "idle"),
        ("unknown", "no_evidence", "unknown"),
    ],
)
def test_listing_projects_only_the_shared_observation(
    monkeypatch, state, reason, expected,
):
    from types import SimpleNamespace
    from src.core.attention.evidence import AttentionVerdict

    manager = _manager_with([("ses_a", "cloude_a")])
    observation = SimpleNamespace(
        verdict=AttentionVerdict(state, reason, "pane"),
        evidence=SimpleNamespace(registry=SimpleNamespace(known=False)),
    )
    seen = []

    def observation_for(session_id, *, now):
        seen.append(session_id)
        return observation

    manager._attention_watcher = SimpleNamespace(observation_for=observation_for)
    monkeypatch.setattr(manager, "_build_tmux_status_map", lambda: _status_rows(["cloude_a"]))
    monkeypatch.setattr(manager, "_instance_index_for_listing", lambda **_kw: None)
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: None)
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: None)
    monkeypatch.setattr(manager, "_is_unread", lambda *_args: False)
    monkeypatch.setattr(manager._owned, "instances_from_db", lambda: set())

    infos = asyncio.run(manager.list_session_infos())
    assert infos[0].activity_status == expected
    assert infos[0].status_source == "pane"
    assert seen == ["ses_a"]
    manager._attention_watcher = None
    assert asyncio.run(manager.list_session_infos())[0].activity_status == "unknown"


def test_the_listing_hands_its_rows_to_the_agent_resweep(monkeypatch):
    name = "cloude_a"
    manager = _manager_with([("ses_a", name)])
    monkeypatch.setattr(manager, "_build_tmux_status_map", lambda: _status_rows([name]))
    monkeypatch.setattr(manager, "_instance_index_for_listing", lambda **_kw: None)
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: None)
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: None)
    monkeypatch.setattr(manager._owned, "instances_from_db", lambda: set())
    offered = []
    monkeypatch.setattr(
        manager._agent_resweep,
        "maybe_schedule",
        lambda mgr, infos: offered.append((mgr, [i.agent_family for i in infos])),
    )

    asyncio.run(manager.list_session_infos())

    assert offered == [(manager, [None])]
