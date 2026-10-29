
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_bra_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_bra_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_ORIGIN_ADOPTED, SESSION_ORIGIN_CREATED
from src.core.session_boot_readopt import (
    ID_SOURCE_DERIVED,
    ID_SOURCE_HOOK_TOKEN,
    READOPT_CANNOT_DETERMINE,
    READOPT_RAN,
    SKIP_ALREADY_HELD,
    SKIP_NO_ROW,
    readopt_surviving_sessions,
)
from src.core.session_identity import record_instance
from src.core.session_manager import SessionManager
from src.core.tmux_backend import SESSION_PREFIX, _slugify
from src.core.tmux_listing import TmuxListing
from src.models import Session
from tests.s7_helpers import migrated_connection

EPOCH_A = 1786913001
EPOCH_B = 1786913002
EPOCH_C = 1786913003




class FakeBackend:

    def __init__(
        self,
        session_id,
        working_dir,
        on_output=None,
        socket_name="cloudetest",
        scrollback_lines=3000,
        session_name=None,
    ):
        self.session_id = session_id
        self.working_dir = working_dir
        self.socket_name = socket_name
        if session_name is not None:
            self.tmux_session = session_name
        else:
            self.tmux_session = f"{SESSION_PREFIX}{_slugify(session_id)}"
        self.attach_calls = 0
        self.needs_pipe_setup = None
        self.rows = []
        self.discover = TmuxListing.answered([])
        self.attachable = TmuxListing.answered([])

    def discover_existing(self):
        return self.discover

    def list_attachable_sessions(self, owned_names=None, owned_instances=None):
        return self.attachable

    def is_alive(self):
        return True

    async def attach_existing(self, needs_pipe_setup=False):
        self.attach_calls += 1
        self.needs_pipe_setup = needs_pipe_setup


def install_backends(monkeypatch, *, discover, attachable):
    built = []

    def factory(settings_obj, session_id, working_dir, on_output=None,
                session_name=None, viewer_probe=None, socket_name_override=None):
        kwargs = {"session_name": session_name}
        if socket_name_override is not None:
            kwargs["socket_name"] = socket_name_override
        backend = FakeBackend(session_id, working_dir, on_output, **kwargs)
        backend.discover = discover
        backend.attachable = attachable
        built.append(backend)
        return backend

    monkeypatch.setattr("src.core.session_manager.build_backend", factory)
    monkeypatch.setattr("src.core.session_backend.build_backend", factory)
    return built


def listing_rows(*specs):
    return TmuxListing.answered(
        [
            {"name": name, "created_at_epoch": epoch, "window_count": 1,
             "created_by_cloude": False, "working_dir": None}
            for name, epoch in specs
        ]
    )




@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    state = tmp_path / "state"
    log_dir.mkdir()
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    config_path = tmp_path / "config.json"
    config_path.write_text('{"session": {"tmux_socket_name": "cloude"}}')
    monkeypatch.setattr(settings, "auth_config_file", str(config_path))
    with closing(migrated_connection(state)):
        pass
    return state


def seed_row(state_dir, manager, *, name, epoch, origin=SESSION_ORIGIN_CREATED,
             working_dir="/tmp", agent_type=None, legacy_session_id=None):
    fields = {"working_dir": working_dir}
    if agent_type:
        fields["agent_type"] = agent_type
    if legacy_session_id:
        fields["legacy_session_id"] = legacy_session_id
    with closing(connect(db_path_for(state_dir))) as conn:
        record_instance(
            conn,
            socket=manager.tmux_socket_name(),
            name=name,
            epoch=epoch,
            origin=origin,
            **fields,
        )
        conn.commit()


async def _noop(*_args, **_kwargs):
    return None




@pytest.mark.asyncio
async def test_every_session_with_a_row_is_held_under_its_stored_id(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    monkeypatch.setattr(mgr, "_sweep_orphan_uploads", _noop)

    for name, epoch in (("cloude_alpha", EPOCH_A), ("cloude_beta", EPOCH_B),
                        ("cloude_gamma", EPOCH_C)):
        seed_row(state_dir, mgr, name=name, epoch=epoch, agent_type="claude")

    mgr.hook_tokens.tmux_names = {
        "ses_alpha": "cloude_alpha",
        "ses_beta": "cloude_beta",
    }

    install_backends(
        monkeypatch,
        discover=TmuxListing.answered(
            ["cloude_alpha", "cloude_beta", "cloude_gamma"]
        ),
        attachable=listing_rows(
            ("cloude_alpha", EPOCH_A),
            ("cloude_beta", EPOCH_B),
            ("cloude_gamma", EPOCH_C),
        ),
    )

    await mgr.lifespan_startup()
    report = await mgr._boot_readopt_task

    assert report.outcome == READOPT_RAN
    assert set(mgr._registry.sessions) == {"ses_alpha", "ses_beta", "adopted:cloude_gamma"}

    by_name = {
        backend.tmux_session: sid for sid, backend in mgr._registry.backends.items()
    }
    assert by_name == {
        "cloude_alpha": "ses_alpha",
        "cloude_beta": "ses_beta",
        "cloude_gamma": "adopted:cloude_gamma",
    }
    assert all(b.attach_calls == 1 for b in mgr._registry.backends.values())
    assert all(b.needs_pipe_setup is True for b in mgr._registry.backends.values())

    assert mgr._registry.sessions["ses_alpha"].agent_type == "claude"
    assert mgr._registry.sessions["ses_alpha"].agent_type_via_fingerprint is False
    assert mgr._registry.sessions["ses_alpha"].created_at == datetime.fromtimestamp(
        EPOCH_A, tz=timezone.utc
    )

    sources = {t.session_id: t.id_source for t in report.plan.targets}
    assert sources["ses_alpha"] == ID_SOURCE_HOOK_TOKEN
    assert sources["adopted:cloude_gamma"] == ID_SOURCE_DERIVED


@pytest.mark.asyncio
async def test_an_adopted_origin_row_is_held_too(state_dir, monkeypatch):
    mgr = SessionManager()
    monkeypatch.setattr(mgr, "_sweep_orphan_uploads", _noop)
    seed_row(
        state_dir, mgr, name="my_own_tmux", epoch=EPOCH_A,
        origin=SESSION_ORIGIN_ADOPTED, legacy_session_id="ses_legacy",
    )
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows(("my_own_tmux", EPOCH_A)),
    )

    report = await readopt_surviving_sessions(mgr)

    assert report.held == ["ses_legacy"]
    assert mgr._registry.backends["ses_legacy"].tmux_session == "my_own_tmux"




@pytest.mark.asyncio
async def test_a_cloude_session_with_no_row_is_not_claimed(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    seed_row(state_dir, mgr, name="cloude_mine", epoch=EPOCH_A)
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows(
            ("cloude_mine", EPOCH_A), ("cloude_stranger", EPOCH_B)
        ),
    )

    report = await readopt_surviving_sessions(mgr)

    assert report.plan.skipped_for(SKIP_NO_ROW) == ["cloude_stranger"]
    held_names = {b.tmux_session for b in mgr._registry.backends.values()}
    assert held_names == {"cloude_mine"}
    owned = mgr._owned.instances() or set()
    assert ("cloude_stranger", EPOCH_B) not in owned
    assert ("cloude_mine", EPOCH_A) in owned




@pytest.mark.asyncio
async def test_a_listing_that_did_not_run_holds_nothing_and_disowns_nothing(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    seed_row(state_dir, mgr, name="cloude_mine", epoch=EPOCH_A)
    before = mgr._owned.instances()

    install_backends(
        monkeypatch,
        discover=TmuxListing.unavailable("tmux_missing"),
        attachable=TmuxListing.unavailable("tmux_missing"),
    )

    report = await readopt_surviving_sessions(mgr)

    assert report.outcome == READOPT_CANNOT_DETERMINE
    assert report.held == []
    assert report.plan is None, "nothing was decided, so there is no plan"
    assert mgr._registry.backends == {}
    assert mgr._owned.instances() == before


@pytest.mark.asyncio
async def test_boot_does_not_even_schedule_the_pass_on_a_failed_probe(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    monkeypatch.setattr(mgr, "_sweep_orphan_uploads", _noop)
    install_backends(
        monkeypatch,
        discover=TmuxListing.unavailable("timeout"),
        attachable=listing_rows(("cloude_mine", EPOCH_A)),
    )

    await mgr.lifespan_startup()

    assert mgr._owned.boot_listing is None
    assert mgr._boot_readopt_task is None
    assert mgr._registry.sessions == {}


@pytest.mark.asyncio
async def test_the_attachable_route_answers_503_with_a_reason(
    state_dir, monkeypatch
):
    from fastapi import HTTPException

    from src.api.session_attach_routes import list_attachable_sessions

    mgr = SessionManager()
    install_backends(
        monkeypatch,
        discover=TmuxListing.unavailable("tmux_missing"),
        attachable=TmuxListing.unavailable("tmux_missing"),
    )

    class _App:
        class state:  # noqa: N801
            session_manager = mgr

    class _Request:
        app = _App

    with pytest.raises(HTTPException) as excinfo:
        await list_attachable_sessions(_Request)

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["listing_reason"] == "tmux_missing"




@pytest.mark.asyncio
async def test_the_metadata_tmux_name_is_what_gets_attached(
    state_dir, monkeypatch
):
    import json

    name = "cloude_Media_Compression"
    sid = f"adopted:{name}"
    payload = Session(
        id=sid, working_dir="/tmp/wd", tmux_session=name, agent_type="claude"
    ).model_dump()
    payload["owned_tmux_sessions"] = [name]
    (state_dir / "session_metadata.json").write_text(
        json.dumps(payload, indent=2, default=str)
    )

    mgr = SessionManager()
    monkeypatch.setattr(mgr, "_sweep_orphan_uploads", _noop)
    assert mgr._registry.current_session() is not None, "metadata did not load"

    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([name]),
        attachable=listing_rows((name, EPOCH_A)),
    )

    await mgr.lifespan_startup()
    if mgr._boot_readopt_task is not None:
        await mgr._boot_readopt_task

    assert sid in mgr._registry.sessions, (
        "the persisted session was dropped; the backend was almost "
        "certainly built for cloude_adopted_cloude_Media_Compression"
    )
    assert mgr._registry.backends[sid].tmux_session == name
    assert (state_dir / "session_metadata.json").exists()


def test_a_metadata_file_without_a_tmux_name_keeps_the_legacy_derivation():
    legacy = Session(id="ses_abc", working_dir="/tmp")
    assert legacy.tmux_session is None
    derived = FakeBackend("ses_abc", "/tmp", session_name=legacy.tmux_session or None)
    assert derived.tmux_session == f"{SESSION_PREFIX}{_slugify('ses_abc')}"




@pytest.mark.asyncio
async def test_running_the_pass_twice_holds_each_session_once(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    seed_row(state_dir, mgr, name="cloude_alpha", epoch=EPOCH_A)
    mgr.hook_tokens.tmux_names = {"ses_alpha": "cloude_alpha"}
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows(("cloude_alpha", EPOCH_A)),
    )

    first = await readopt_surviving_sessions(mgr)
    second = await readopt_surviving_sessions(mgr)

    assert first.held == ["ses_alpha"]
    assert second.held == []
    assert second.plan.skipped_for(SKIP_ALREADY_HELD) == ["cloude_alpha"]
    assert list(mgr._registry.sessions) == ["ses_alpha"]
    assert mgr._registry.backends["ses_alpha"].attach_calls == 1


@pytest.mark.asyncio
async def test_a_session_registered_ahead_of_this_pass_still_gets_its_epoch(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    name = "cloude_PT-IMC"
    backend = FakeBackend("ses_legacy", "/tmp", session_name=name)
    mgr._registry.backends["ses_legacy"] = backend
    mgr._registry.sessions["ses_legacy"] = Session(id="ses_legacy", working_dir="/tmp")
    assert "ses_legacy" not in mgr._instance_epochs, (
        "the legacy path never writes this - that is the whole defect"
    )
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows((name, EPOCH_A)),
    )

    report = await readopt_surviving_sessions(mgr)

    assert report.plan.skipped_for(SKIP_ALREADY_HELD) == [name]
    assert report.held == []
    assert backend.attach_calls == 0
    assert mgr._instance_epochs["ses_legacy"] == EPOCH_A


@pytest.mark.asyncio
async def test_a_bare_rehydrated_pointer_does_not_keep_its_pane_from_being_held(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    name = "cloude_sh-9"
    seed_row(state_dir, mgr, name=name, epoch=EPOCH_A)
    mgr.hook_tokens.tmux_names = {"ses_shell9": name}
    mgr._registry.register(Session(id="ses_shell9", working_dir="/tmp", tmux_session=name), backend=None)
    install_backends(
        monkeypatch, discover=TmuxListing.answered([]), attachable=listing_rows((name, EPOCH_A)))

    report = await readopt_surviving_sessions(mgr)

    assert report.held == ["ses_shell9"]
    assert mgr._registry.backends["ses_shell9"].attach_calls == 1


@pytest.mark.asyncio
async def test_one_refused_pane_does_not_take_the_others_down(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    for name, epoch in (("cloude_alpha", EPOCH_A), ("cloude_dead", EPOCH_B)):
        seed_row(state_dir, mgr, name=name, epoch=epoch)
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows(
            ("cloude_alpha", EPOCH_A), ("cloude_dead", EPOCH_B)
        ),
    )

    original = FakeBackend.attach_existing

    async def refusing(self, needs_pipe_setup=False):
        if self.tmux_session == "cloude_dead":
            raise RuntimeError("cannot adopt cloude_dead: pane already dead")
        await original(self, needs_pipe_setup=needs_pipe_setup)

    monkeypatch.setattr(FakeBackend, "attach_existing", refusing)

    report = await readopt_surviving_sessions(mgr)

    assert report.held == ["adopted:cloude_alpha"]
    assert [name for name, _err in report.failed] == ["cloude_dead"]
    assert "adopted:cloude_dead" not in mgr._registry.sessions




@pytest.mark.asyncio
async def test_a_hook_for_a_re_adopted_session_raises_a_toast(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    seed_row(state_dir, mgr, name="cloude_alpha", epoch=EPOCH_A)
    mgr.hook_tokens.tmux_names = {"ses_alpha": "cloude_alpha"}
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows(("cloude_alpha", EPOCH_A)),
    )

    with pytest.raises(ValueError):
        mgr.record_toast(
            session_id="ses_alpha", kind="Stop", title="t", body="b"
        )

    await readopt_surviving_sessions(mgr)

    toast = mgr.record_toast(
        session_id="ses_alpha", kind="Stop", title="t", body="b"
    )
    assert toast is not None
    assert mgr._instance_epochs["ses_alpha"] == EPOCH_A


@pytest.mark.asyncio
async def test_the_current_session_pointer_is_not_decided_by_a_race(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    for name, epoch in (("cloude_alpha", EPOCH_A), ("cloude_beta", EPOCH_B)):
        seed_row(state_dir, mgr, name=name, epoch=epoch)
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows(
            ("cloude_alpha", EPOCH_A), ("cloude_beta", EPOCH_B)
        ),
    )

    mgr._registry.register(
        Session(id="ses_rehydrated", working_dir="/tmp",
                tmux_session="cloude_rehydrated"),
        None,
    )
    assert mgr._registry.current_session().id == "ses_rehydrated"

    await readopt_surviving_sessions(mgr)

    assert mgr._registry.current_session().id == "ses_rehydrated"
    assert len(mgr._registry.sessions) == 3


@pytest.mark.asyncio
async def test_with_no_prior_current_the_pointer_is_deterministic(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    for name, epoch in (("cloude_alpha", EPOCH_A), ("cloude_beta", EPOCH_B)):
        seed_row(state_dir, mgr, name=name, epoch=epoch)
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows(
            ("cloude_alpha", EPOCH_A), ("cloude_beta", EPOCH_B)
        ),
    )

    await readopt_surviving_sessions(mgr)

    assert mgr._registry.current_session().id == "adopted:cloude_alpha"


@pytest.mark.asyncio
async def test_a_session_entered_during_the_pass_keeps_the_pointer(
    state_dir, monkeypatch
):
    mgr = SessionManager()
    for name, epoch in (("cloude_alpha", EPOCH_A), ("cloude_beta", EPOCH_B)):
        seed_row(state_dir, mgr, name=name, epoch=epoch)
    install_backends(
        monkeypatch,
        discover=TmuxListing.answered([]),
        attachable=listing_rows(
            ("cloude_alpha", EPOCH_A), ("cloude_beta", EPOCH_B)
        ),
    )

    register = mgr._registry.register
    registered = []

    def register_then_maybe_user_creates(session, backend):
        register(session, backend)
        registered.append(session.id)
        if len(registered) == 2:
            register(
                Session(
                    id="ses_user_made",
                    working_dir="/tmp",
                    tmux_session="cloude_user_made",
                ),
                None,
            )

    monkeypatch.setattr(
        mgr._registry, "register", register_then_maybe_user_creates
    )

    await readopt_surviving_sessions(mgr)

    assert mgr._registry.current_session().id == "ses_user_made"
