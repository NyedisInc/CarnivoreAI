
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ghost_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ghost_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.product_identity import TMUX_SESSION_PREFIX
from src.core.session_ghost_reap import measured_gone, snapshot_registrations
from src.core.session_name_claim import claim_tmux_name
from src.core.session_status_map import StatusMap
from src.core.sessions.hook_token_authority import HookTokenAuthority
from src.core.tmux_listing import (
    REASON_NO_SERVER,
    TmuxListing,
    classify_listing_failure,
)
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

SOCK = "cloude"


class _Backend:

    def __init__(self, name, socket=SOCK):
        self.tmux_session = name
        self.socket_name = socket


def _complete(*names, socket=SOCK):
    return StatusMap({n: {"name": n} for n in names}, complete=True, socket=socket)




def test_complete_listing_without_the_name_is_gone():
    ghost, live = _Backend("cloude_a"), _Backend("cloude_b")
    backends = {"g": ghost, "l": live}
    snap = snapshot_registrations(backends)
    gone = measured_gone(snap, backends, _complete("cloude_b"))
    assert [r.session_id for r in gone] == ["g"]


def test_whole_server_gone_is_a_complete_answer_of_zero():
    backends = {"a": _Backend("cloude_a"), "b": _Backend("cloude_b")}
    snap = snapshot_registrations(backends)
    gone = measured_gone(snap, backends, _complete())
    assert sorted(r.session_id for r in gone) == ["a", "b"]


def test_unknown_listing_reaps_nothing():
    backends = {"a": _Backend("cloude_a")}
    snap = snapshot_registrations(backends)
    assert measured_gone(snap, backends, StatusMap()) == []
    assert measured_gone(snap, backends, {}) == []


def test_listing_of_another_socket_or_no_socket_reaps_nothing():
    backends = {"a": _Backend("cloude_a")}
    snap = snapshot_registrations(backends)
    assert measured_gone(snap, backends, _complete(socket="other")) == []
    assert measured_gone(snap, backends, _complete(socket=None)) == []


def test_registration_changed_during_the_listing_is_not_reaped():
    old = _Backend("cloude_a")
    backends = {"a": old, "r": _Backend("cloude_r")}
    snap = snapshot_registrations(backends)
    backends["a"] = _Backend("cloude_a")
    backends["r"].tmux_session = "cloude_renamed"
    assert measured_gone(snap, backends, _complete()) == []


def test_pty_backend_is_never_judged_by_a_tmux_listing():
    class _Pty:
        pass

    backends = {"p": _Pty()}
    assert snapshot_registrations(backends) == ()




def _listing(*names, refused=0):
    return TmuxListing.answered(
        [{"name": n} for n in names], refused_rows=refused
    )


def test_recreate_gets_its_own_measured_free_name_back():
    claim = claim_tmux_name(
        "cloude_x",
        listing=_listing("cloude_y"),
        active_names={"cloude_x"},
        owned_names={"cloude_x"},
        recreate=True,
    )
    assert claim.name == "cloude_x"
    assert claim.reclaimed is True


def test_live_holder_still_forces_a_suffix_on_a_recreate():
    claim = claim_tmux_name(
        "cloude_x",
        listing=_listing("cloude_x"),
        active_names=set(),
        owned_names={"cloude_x"},
        recreate=True,
    )
    assert claim.name == "cloude_x-2"
    assert claim.reclaimed is False


def test_unknown_or_partial_listing_grants_nothing():
    for listing in (TmuxListing.unavailable("probe_error"), _listing(refused=1)):
        claim = claim_tmux_name(
            "cloude_x",
            listing=listing,
            active_names={"cloude_x"},
            owned_names=set(),
            recreate=True,
        )
        assert claim.name == "cloude_x-2"


def test_fresh_create_keeps_the_owned_reservation():
    claim = claim_tmux_name(
        "cloude_x",
        listing=_listing(),
        active_names=set(),
        owned_names={"cloude_x"},
        recreate=False,
    )
    assert claim.name == "cloude_x-2"




def test_release_drops_only_a_binding_that_still_names_the_gone_instance(tmp_path):
    auth = HookTokenAuthority(lambda: tmp_path)
    auth.mint("ses_old", tmux_name="cloude_x")
    auth.mint("ses_moved", tmux_name="cloude_y")
    assert auth.release("ses_old", tmux_name="cloude_x") is True
    assert "ses_old" not in auth.tmux_names and "ses_old" not in auth.tokens
    assert auth.release("ses_moved", tmux_name="cloude_x") is False
    assert auth.tmux_names["ses_moved"] == "cloude_y"
    assert "ses_old" not in HookTokenAuthority(lambda: tmp_path).tmux_names




def _tmux(*args):
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, check=False
    )


_SERVER_GONE_DEADLINE_S: float = 15.0


def _kill_server_and_wait_gone():
    assert _tmux("kill-server").returncode == 0
    deadline = time.monotonic() + _SERVER_GONE_DEADLINE_S
    last = ""
    while time.monotonic() < deadline:
        probe = _tmux("list-sessions")
        last = probe.stderr.decode("utf-8", errors="replace").strip()
        if probe.returncode != 0:
            listing = classify_listing_failure(probe.returncode, last)
            if listing.ok and listing.reason == REASON_NO_SERVER:
                return
        time.sleep(0.05)
    pytest.fail(
        f"killed tmux server not measured gone within "
        f"{_SERVER_GONE_DEADLINE_S}s; last stderr: {last!r}"
    )


def _manager():
    from src.core.session_manager import SessionManager

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        return SessionManager()


async def _create(sm, project, wd, **kw):
    return await sm.create_session(
        session_id=f"ses_{secrets.token_hex(4)}",
        working_dir=str(wd),
        auto_start_claude=False,
        copy_templates=False,
        project_name=project,
        **kw,
    )


async def _teardown(sm):
    from src.core.session_ghost_reap import drop_registration

    _tmux("kill-server")
    for sid in list(sm._registry.backends):
        await drop_registration(sm, sid, reason="test_teardown")


@requires_tmux
@pytest.mark.asyncio
async def test_is_alive_does_not_prefix_match(tmp_path):
    from src.core.session_backend import build_backend

    name = f"{TMUX_SESSION_PREFIX}pfx_{secrets.token_hex(3)}"
    assert _tmux("new-session", "-d", "-s", f"{name}-2").returncode == 0
    try:
        ghost = build_backend(
            None, session_id="g", working_dir=tmp_path, on_output=None,
            session_name=name, socket_name_override=TEST_SOCKET_NAME,
        )
        twin = build_backend(
            None, session_id="t", working_dir=tmp_path, on_output=None,
            session_name=f"{name}-2", socket_name_override=TEST_SOCKET_NAME,
        )
        assert ghost.is_alive() is False
        assert twin.is_alive() is True
    finally:
        _tmux("kill-server")


@requires_tmux
@pytest.mark.asyncio
async def test_killed_server_reaps_registrations_and_recreate_keeps_the_name(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))
    project = f"ghost_{secrets.token_hex(4)}"
    name = f"{TMUX_SESSION_PREFIX}{project}"
    sm = _manager()
    try:
        first = await _create(sm, project, tmp_path)
        assert sm._registry.backends[first.id].tmux_session == name

        _kill_server_and_wait_gone()
        await sm.list_session_infos()
        assert first.id not in sm._registry.backends, "ghost registration kept"
        assert name not in sm.active_tmux_names()

        again = await _create(sm, name, tmp_path, reuse_session_id=987654)
        assert sm._registry.backends[again.id].tmux_session == name
        assert sm._registry.registered_ids_for_tmux_name(name) == [again.id]
    finally:
        await _teardown(sm)


@requires_tmux
@pytest.mark.asyncio
async def test_recreate_reclaims_even_before_any_listing_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))
    project = f"ghost_{secrets.token_hex(4)}"
    name = f"{TMUX_SESSION_PREFIX}{project}"
    sm = _manager()
    try:
        first = await _create(sm, project, tmp_path)
        _kill_server_and_wait_gone()
        again = await _create(sm, name, tmp_path, reuse_session_id=987654)
        assert sm._registry.backends[again.id].tmux_session == name
        assert first.id not in sm._registry.backends
        assert sm.hook_tokens.name_for(first.id) is None
        assert sm.hook_tokens.name_for(again.id) == name
    finally:
        await _teardown(sm)


@requires_tmux
@pytest.mark.asyncio
async def test_live_holder_still_suffixes_and_nothing_live_is_reaped(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))
    project = f"held_{secrets.token_hex(4)}"
    name = f"{TMUX_SESSION_PREFIX}{project}"
    sm = _manager()
    try:
        first = await _create(sm, project, tmp_path)
        await sm.list_session_infos()
        assert first.id in sm._registry.backends, "a live session was reaped"
        again = await _create(sm, name, tmp_path, reuse_session_id=987654)
        assert sm._registry.backends[again.id].tmux_session == f"{name}-2"
        assert first.id in sm._registry.backends
    finally:
        await _teardown(sm)
