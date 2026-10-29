
from __future__ import annotations

import asyncio
import shlex
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from unittest import mock

import pytest



os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tests_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tests_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.session_backend import SessionBackend, build_backend
from src.core.tmux_backend import (
    INITIAL_COLS,
    INITIAL_ROWS,
    PaneDeadError,
    TmuxBackend,
    _has_control_chars,
    _slugify,
)
from src.utils.pty_session import PTYBackend
from src.core import tmux_discovery
from src.core.pipe_liveness import PIPE_OWNER_OPTION
from src.core.product_identity import TMUX_SESSION_PREFIX
from tests.socket_guard import TEST_SOCKET_NAME


TMUX_AVAILABLE = shutil.which("tmux") is not None
requires_tmux = pytest.mark.skipif(not TMUX_AVAILABLE, reason="tmux not on PATH")




def test_slugify_replaces_dots():
    assert "." not in _slugify("my.project.name")
    assert _slugify("my.project") == "my_project"


def test_slugify_handles_mixed_invalid_chars():
    assert _slugify("hello world:foo/bar.baz") == "hello_world_foo_bar_baz"


def test_slugify_preserves_alphanumeric_and_dash_underscore():
    assert _slugify("My-Session_42") == "My-Session_42"


def test_slugify_empty_input_returns_default():
    assert _slugify("") == "default"
    assert _slugify("...") == "default"




def test_has_control_chars_flags_etx():
    assert _has_control_chars(b"\x03hello")


def test_has_control_chars_flags_escape():
    assert _has_control_chars(b"\x1b[A")


def test_has_control_chars_ignores_whitespace():
    assert not _has_control_chars(b"hello\tworld\n")
    assert not _has_control_chars(b"line1\r\nline2")


def test_has_control_chars_flags_del():
    assert _has_control_chars(b"foo\x7fbar")




def test_pty_backend_is_session_backend():
    backend = PTYBackend(
        session_id="test",
        working_dir=Path.home(),
        on_output=None,
    )
    assert isinstance(backend, SessionBackend)


def test_pty_backend_discover_existing_is_empty():
    backend = PTYBackend("test", Path.home(), None)
    listing = backend.discover_existing()
    assert listing.ok is True
    assert listing.sessions == []
    assert listing.reason == "not_applicable"


def test_pty_backend_capture_scrollback_is_empty():
    backend = PTYBackend("test", Path.home(), None)
    assert backend.capture_scrollback() == b""


def test_pty_backend_required_methods_are_present():
    backend = PTYBackend("test", Path.home(), None)
    for name in (
        "start",
        "stop",
        "write",
        "resize",
        "is_alive",
        "read_async",
        "discover_existing",
        "capture_scrollback",
    ):
        assert callable(getattr(backend, name)), f"missing {name}"




def test_build_backend_falls_back_to_pty_when_tmux_missing():
    tmux_discovery.reset_probe_cache()
    with mock.patch(
        "src.core.tmux_discovery.resolve_tmux_path", return_value=None
    ):
        backend = build_backend(
            settings_obj=None,
            session_id="fallback-test",
            working_dir=Path.home(),
            on_output=None,
        )
        assert isinstance(backend, PTYBackend), (
            f"expected PTYBackend fallback, got {type(backend).__name__}"
        )


def test_build_backend_force_pty_even_when_tmux_present():
    class StubSettings:
        def load_auth_config(self):
            class AC:
                class session:
                    backend = "pty"
                    tmux_socket_name = _TEST_SOCKET
                    scrollback_lines = 3000
            return AC()

    backend = build_backend(
        settings_obj=StubSettings(),
        session_id="forced-pty",
        working_dir=Path.home(),
        on_output=None,
    )
    assert isinstance(backend, PTYBackend)


@requires_tmux
def test_build_backend_auto_picks_tmux_when_available():
    backend = build_backend(
        settings_obj=None,
        session_id="auto-pick",
        working_dir=Path.home(),
        on_output=None,
    )
    assert isinstance(backend, TmuxBackend)


@requires_tmux
def test_build_backend_logs_the_same_selection_at_info_once():
    from structlog.testing import capture_logs
    from src.core import session_backend

    session_backend._SELECTION_LOGGED.clear()
    with capture_logs() as logs:
        for name in ("log-once-a", "log-once-b", "log-once-c"):
            build_backend(settings_obj=None, session_id=name,
                          working_dir=Path.home(), on_output=None)
    selected = [e for e in logs if e.get("event") == "session_backend_selected"]
    assert selected, "no selection was logged at all"
    assert [e["log_level"] for e in selected if e["log_level"] == "info"] == ["info"]
    assert all(e["log_level"] == "debug" for e in selected[1:])


@requires_tmux
def test_build_backend_honors_configured_socket_name():
    configured = f"cloude_regress_{uuid.uuid4().hex[:8]}"
    assert configured != "cloude"

    class StubSettings:
        def load_auth_config(self):
            class AC:
                class session:
                    backend = "tmux"
                    tmux_socket_name = configured
                    scrollback_lines = 100

            return AC()

    backend = build_backend(
        settings_obj=StubSettings(),
        session_id=f"socket-honor-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
    )
    assert isinstance(backend, TmuxBackend)
    assert backend.socket_name == configured, (
        f"build_backend must honor the configured tmux_socket_name; "
        f"expected {configured!r}, got {backend.socket_name!r}"
    )


@requires_tmux
def test_build_backend_defaults_to_cloude_socket_with_no_settings():
    from src.core.tmux_backend import DEFAULT_SOCKET_NAME
    from tests.socket_guard import shipped_default_socket_name

    backend = build_backend(
        settings_obj=None,
        session_id=f"socket-default-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
    )
    assert isinstance(backend, TmuxBackend)
    assert backend.socket_name == DEFAULT_SOCKET_NAME

    assert shipped_default_socket_name() == "carnivore"


@requires_tmux
def test_build_backend_create_and_adopt_agree_on_socket(tmux_socket_cleanup):

    class StubSettings:
        def load_auth_config(self):
            class AC:
                class session:
                    backend = "tmux"
                    tmux_socket_name = tmux_socket_cleanup
                    scrollback_lines = 100

            return AC()

    settings_obj = StubSettings()
    created = build_backend(
        settings_obj=settings_obj,
        session_id=f"agree-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
        session_name=f"cloude_agree_{uuid.uuid4().hex[:6]}",
    )
    try:
        asyncio.run(created.start())

        adopt_socket = settings_obj.load_auth_config().session.tmux_socket_name
        assert created.socket_name == adopt_socket, (
            "create and adopt resolved DIFFERENT sockets — split-brain"
        )

        adopted = TmuxBackend.for_external(
            session_name=created.tmux_session,
            working_dir=Path.home(),
            on_output=None,
            socket_name=adopt_socket,
        )
        asyncio.run(adopted.attach_existing(needs_pipe_setup=True))
        assert adopted.is_alive(), (
            "adopt could not find the session create just started on "
            "the same configured socket"
        )
        asyncio.run(adopted.stop())
    finally:
        asyncio.run(created.stop())




_TEST_SOCKET = TEST_SOCKET_NAME


@pytest.fixture
def tmux_socket_cleanup():
    yield _TEST_SOCKET
    try:
        import subprocess
        subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "kill-server"],
            capture_output=True,
            check=False,
        )
    except Exception:
        pass


@requires_tmux
def test_tmux_backend_discover_existing_finds_created_session(tmux_socket_cleanup):
    backend = TmuxBackend(
        session_id=f"discovery-test-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    try:
        asyncio.run(backend.start())
        listing = backend.discover_existing()
        assert listing.ok is True
        names = listing.sessions
        assert backend.tmux_session in names, (
            f"expected {backend.tmux_session} in {names}"
        )
        assert backend.is_alive()
    finally:
        asyncio.run(backend.stop())


@requires_tmux
def test_tmux_backend_write_large_paste_delivers_content_to_pane(tmux_socket_cleanup):
    backend = TmuxBackend(
        session_id=f"bigpaste-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )

    async def _inner():
        await backend.start(command="/bin/cat")
        await asyncio.sleep(0.3)

        payload = b"abc" * 700
        await backend.write(payload)

        await asyncio.sleep(0.8)

        cap = backend.capture_scrollback(lines=500)
        text = cap.decode("utf-8", errors="replace")

        assert "abc" in text, (
            f"expected 'abc' in capture, got {len(cap)} bytes: {text[:200]!r}"
        )
        assert backend.is_alive()

    try:
        asyncio.run(_inner())
    finally:
        asyncio.run(backend.stop())


@requires_tmux
def test_tmux_backend_write_leading_dash_payloads_land_verbatim(tmux_socket_cleanup):
    payloads = ["- hello", "-hello", "--foo", "-l", "--"]
    backend = TmuxBackend(
        session_id=f"dash180-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )

    async def _inner():
        await backend.start(command="/bin/cat")
        await asyncio.sleep(0.3)

        for payload in payloads:
            await backend.write(payload.encode("utf-8"))
            await backend.write(b"\n")

        await asyncio.sleep(0.8)

        raw = backend.capture_scrollback(lines=500).decode("utf-8", errors="replace")
        plain = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw)
        lines = [line.strip() for line in plain.splitlines()]

        for payload in payloads:
            assert payload in lines, (
                f"payload {payload!r} never reached the pane as its own "
                f"line; captured lines: {lines[:24]!r}"
            )

    try:
        asyncio.run(_inner())
    finally:
        asyncio.run(backend.stop())




def _make_backend_for_write_tests() -> TmuxBackend:
    backend = TmuxBackend(
        session_id=f"write-routing-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
    )
    backend._running = True
    return backend


def _patch_run_tmux(backend: TmuxBackend):
    calls: list[tuple] = []

    async def fake(*args, stdin_bytes=None, check=True):
        calls.append(tuple(shlex.split(stdin_bytes.decode())) if args == ("source-file", "-") else args)
        backend.raw_calls.append(args)  # type: ignore[attr-defined]
        return 0, b"", b""

    backend.raw_calls = []  # type: ignore[attr-defined]

    backend._run_tmux = fake  # type: ignore[assignment]
    return calls


def test_tmux_backend_write_plain_text_uses_send_keys_l():
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    asyncio.run(backend.write(b"hello"))

    assert len(calls) == 1, f"expected exactly 1 tmux call, got {len(calls)}"
    argv = calls[0]
    assert argv[0] == "send-keys"
    assert argv[1] == "-l"
    assert argv[2] == "-t"
    assert argv[3] == f"={backend.tmux_session}:"
    assert argv[4] == "--"
    assert argv[5] == "hello"


def test_tmux_backend_write_leading_dash_text_gets_end_of_options_marker():
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    asyncio.run(backend.write(b"- hello"))

    assert len(calls) == 1, f"expected exactly 1 tmux call, got {len(calls)}"
    argv = calls[0]
    assert argv[0] == "send-keys"
    assert argv[1] == "-l"
    assert argv[2] == "-t"
    assert argv[3] == f"={backend.tmux_session}:"
    assert argv[4] == "--", f"no end-of-options marker before the text: {argv!r}"
    assert argv[5] == "- hello"
    assert len(argv) == 6, f"unexpected extra argv elements: {argv!r}"


def test_tmux_backend_write_backspace_uses_hex_keys():
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    asyncio.run(backend.write(b"\x7f"))

    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == "send-keys"
    assert argv[1] == "-H"
    assert argv[2] == "-t"
    assert argv[3] == f"={backend.tmux_session}:"
    assert argv[4:] == ("7f",), f"expected hex pair '7f', got trailing {argv[4:]}"


def test_tmux_backend_write_escape_single_byte():
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    asyncio.run(backend.write(b"\x1b"))

    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == "send-keys"
    assert argv[1] == "-H"
    assert argv[4:] == ("1b",)


def test_tmux_backend_write_arrow_sequence_no_paste_wrap():
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    asyncio.run(backend.write(b"\x1b[A"))

    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == "send-keys"
    assert argv[1] == "-H"
    assert argv[4:] == ("1b", "5b", "41"), f"expected 1b 5b 41, got {argv[4:]}"


def test_tmux_backend_write_ctrl_c_uses_hex_keys():
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    asyncio.run(backend.write(b"\x03"))

    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == "send-keys"
    assert argv[1] == "-H"
    assert argv[4:] == ("03",)


def test_tmux_backend_write_shift_tab_uses_hex_keys():
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    asyncio.run(backend.write(b"\x1b[Z"))

    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == "send-keys"
    assert argv[1] == "-H"
    assert argv[4:] == ("1b", "5b", "5a")


def test_tmux_backend_write_large_payload_uses_load_and_paste_buffer():
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    payload = b"A" * 500
    asyncio.run(backend.write(payload))

    assert len(calls) == 2, f"paste path should issue two tmux calls, got {len(calls)}"
    load_argv, paste_argv = calls
    assert load_argv[0] == "load-buffer"
    assert "-b" in load_argv
    assert load_argv[-1] == "-"
    assert paste_argv[0] == "paste-buffer"
    assert "-d" in paste_argv
    assert "-r" in paste_argv
    assert "-p" not in paste_argv
    assert "-b" in paste_argv
    assert "-t" in paste_argv


def test_tmux_backend_write_empty_is_noop():
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    asyncio.run(backend.write(b""))

    assert calls == [], f"empty write must be a no-op, got {calls}"


def test_tmux_backend_write_raises_when_not_running():
    backend = TmuxBackend(
        session_id=f"not-running-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
    )
    with pytest.raises(RuntimeError, match="not running"):
        asyncio.run(backend.write(b"hello"))


@requires_tmux
def test_tmux_backend_is_alive_lifecycle(tmux_socket_cleanup):
    backend = TmuxBackend(
        session_id=f"alive-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    assert not backend.is_alive()
    try:
        asyncio.run(backend.start())
        assert backend.is_alive()
    finally:
        asyncio.run(backend.stop())
    time.sleep(0.2)
    assert not backend.is_alive()


@requires_tmux
@pytest.mark.asyncio
async def test_tmux_backend_resize_actually_resizes_window(tmux_socket_cleanup):
    slug = f"resize_test_{secrets.token_hex(4)}"
    wd = Path(tempfile.mkdtemp(prefix="cc_resize_"))
    backend = TmuxBackend(
        session_id=slug,
        working_dir=wd,
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    try:
        await backend.start()

        out = subprocess.check_output(
            [
                "tmux",
                "-L",
                backend.socket_name,
                "display-message",
                "-t",
                backend.tmux_session,
                "-p",
                "#{window_width}x#{window_height}",
            ]
        ).decode().strip()
        assert out == f"{INITIAL_COLS}x{INITIAL_ROWS}", f"initial dims wrong: {out}"

        backend.resize(cols=100, rows=30)
        await asyncio.sleep(0.3)

        out = subprocess.check_output(
            [
                "tmux",
                "-L",
                backend.socket_name,
                "display-message",
                "-t",
                backend.tmux_session,
                "-p",
                "#{window_width}x#{window_height}",
            ]
        ).decode().strip()
        assert out == "100x30", f"after resize dims wrong: {out}"
    finally:
        await backend.stop()


@requires_tmux
@pytest.mark.asyncio
async def test_tmux_backend_start_honors_initial_dims(tmux_socket_cleanup):
    slug = f"initdims_{secrets.token_hex(4)}"
    wd = Path(tempfile.mkdtemp(prefix="cc_initdims_"))
    backend = TmuxBackend(
        session_id=slug,
        working_dir=wd,
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    try:
        await backend.start(initial_cols=100, initial_rows=30)

        out = subprocess.check_output(
            [
                "tmux",
                "-L",
                backend.socket_name,
                "display-message",
                "-t",
                backend.tmux_session,
                "-p",
                "#{window_width}x#{window_height}",
            ]
        ).decode().strip()
        assert out == "100x30", (
            f"expected 100x30 from initial_cols/initial_rows override, got {out} "
            f"(default would be {INITIAL_COLS}x{INITIAL_ROWS})"
        )
    finally:
        await backend.stop()


@requires_tmux
@pytest.mark.asyncio
async def test_tmux_backend_start_ignores_one_sided_initial_dims(tmux_socket_cleanup):
    slug = f"onesided_{secrets.token_hex(4)}"
    wd = Path(tempfile.mkdtemp(prefix="cc_onesided_"))
    backend = TmuxBackend(
        session_id=slug,
        working_dir=wd,
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    try:
        await backend.start(initial_cols=100, initial_rows=None)

        out = subprocess.check_output(
            [
                "tmux",
                "-L",
                backend.socket_name,
                "display-message",
                "-t",
                backend.tmux_session,
                "-p",
                "#{window_width}x#{window_height}",
            ]
        ).decode().strip()
        assert out == f"{INITIAL_COLS}x{INITIAL_ROWS}", (
            f"asymmetric dims should fall back to defaults, got {out}"
        )
    finally:
        await backend.stop()


@requires_tmux
@pytest.mark.asyncio
async def test_tmux_backend_write_ctrl_l_single_byte(tmux_socket_cleanup):
    backend = TmuxBackend(
        session_id=f"ctrll_{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )

    async def _inner():
        await backend.start(command="/bin/cat")
        await asyncio.sleep(0.3)

        await backend.write(b"\x0c")
        await asyncio.sleep(0.5)

        assert backend.is_alive(), "pane died after Ctrl+L write"

    try:
        await _inner()
    finally:
        await backend.stop()




@requires_tmux
@pytest.mark.asyncio
async def test_tmux_backend_attach_existing_flips_running(tmux_socket_cleanup):
    slug = f"attach_flip_{secrets.token_hex(4)}"
    wd = Path(tempfile.mkdtemp(prefix="cc_attach_"))
    first = TmuxBackend(
        session_id=slug,
        working_dir=wd,
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    try:
        await first.start()
        assert first.is_alive()

        second = TmuxBackend(
            session_id=slug,
            working_dir=wd,
            on_output=None,
            socket_name=tmux_socket_cleanup,
        )
        assert second._running is False, "fresh instance must start with _running=False"
        assert second.tmux_session in second.discover_existing().sessions

        await second.attach_existing()

        assert second._running is True, "attach_existing must flip _running=True"
        assert second.is_alive(), "attached instance must see the live tmux session"

        await second.attach_existing()
        assert second._running is True
    finally:
        try:
            await second.stop()
        except Exception:
            pass
        try:
            await first.stop()
        except Exception:
            pass


@requires_tmux
@pytest.mark.asyncio
async def test_tmux_backend_attach_existing_raises_if_session_gone(tmux_socket_cleanup):
    slug = f"attach_gone_{secrets.token_hex(4)}"
    wd = Path(tempfile.mkdtemp(prefix="cc_attach_gone_"))
    backend = TmuxBackend(
        session_id=slug,
        working_dir=wd,
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    assert not backend.is_alive()
    with pytest.raises(RuntimeError, match="is not alive"):
        await backend.attach_existing()
    assert backend._running is False


@requires_tmux
@pytest.mark.asyncio
async def test_tmux_backend_attach_existing_write_works_after(tmux_socket_cleanup):
    slug = f"attach_write_{secrets.token_hex(4)}"
    wd = Path(tempfile.mkdtemp(prefix="cc_attach_write_"))
    first = TmuxBackend(
        session_id=slug,
        working_dir=wd,
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    second = TmuxBackend(
        session_id=slug,
        working_dir=wd,
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    try:
        await first.start(command="/bin/cat")
        await asyncio.sleep(0.2)

        await second.attach_existing()

        await second.write(b"\x7f")
        await second.write(b"hello")

        assert second.is_alive()
    finally:
        try:
            await second.stop()
        except Exception:
            pass
        try:
            await first.stop()
        except Exception:
            pass


@requires_tmux
@pytest.mark.asyncio
async def test_attach_existing_refuses_a_husk_the_process_exited_in(
    tmux_socket_cleanup,
):
    slug = f"attach_husk_{secrets.token_hex(4)}"
    wd = Path(tempfile.mkdtemp(prefix="cc_attach_husk_"))
    first = TmuxBackend(
        session_id=slug,
        working_dir=wd,
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    try:
        await first.start(command="/bin/sh")
        assert first.is_alive()

        await first.write(b"exit\r")

        target = first.tmux_session
        for _ in range(50):
            rc, out, _ = await first._run_tmux(
                "display-message", "-t", target, "-p", "#{pane_dead}",
                check=False,
            )
            if rc == 0 and out.decode().strip() == "1":
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("pane never reported #{pane_dead}=1 within 5s")

        rc, _, _ = await first._run_tmux(
            "has-session", "-t", target, check=False
        )
        assert rc == 0, "the tmux session must survive its pane's process"

        adopted = TmuxBackend.for_external(
            session_name=target,
            working_dir=wd,
            on_output=None,
            socket_name=tmux_socket_cleanup,
        )
        with pytest.raises(PaneDeadError, match="pane already dead"):
            await adopted.attach_existing(needs_pipe_setup=True)
        assert adopted._running is False, (
            "a refused adopt must not claim the backend is streamable"
        )
    finally:
        try:
            await first.stop()
        except Exception:
            pass


def test_pty_backend_attach_existing_raises_not_implemented():
    backend = PTYBackend("attach-not-impl", Path.home(), None)
    with pytest.raises(NotImplementedError, match="does not persist"):
        asyncio.run(backend.attach_existing())



from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402




@requires_tmux
def test_list_attachable_sessions_flags_ownership_correctly(tmux_socket_cleanup):
    owned_backend = TmuxBackend(
        session_id=f"owned-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
        socket_name=tmux_socket_cleanup,
    )
    external_name = f"external_test_{secrets.token_hex(4)}"

    try:
        asyncio.run(owned_backend.start())

        subprocess.run(
            ["tmux", "-L", tmux_socket_cleanup, "new-session",
             "-d", "-s", external_name],
            check=True,
            capture_output=True,
        )

        listing = owned_backend.list_attachable_sessions(
            owned_names={owned_backend.tmux_session}
        )
        assert listing.ok is True, (
            f"live tmux listing must be evaluable; got {listing!r}"
        )
        by_name = {r["name"]: r for r in listing.sessions}

        assert owned_backend.tmux_session in by_name, (
            f"owned session missing from listing; got {sorted(by_name)}"
        )
        assert external_name in by_name, (
            f"external session missing from listing; got {sorted(by_name)}"
        )

        assert by_name[owned_backend.tmux_session]["created_by_cloude"] is True, (
            "owned session must be flagged created_by_cloude=True"
        )
        assert by_name[external_name]["created_by_cloude"] is False, (
            "external session must be flagged created_by_cloude=False"
        )

        assert by_name[owned_backend.tmux_session]["window_count"] >= 1
        assert by_name[external_name]["window_count"] >= 1
    finally:
        subprocess.run(
            ["tmux", "-L", tmux_socket_cleanup, "kill-session",
             "-t", external_name],
            check=False,
            capture_output=True,
        )
        try:
            asyncio.run(owned_backend.stop())
        except Exception:
            pass




def test_ensure_pipe_pane_replaces_existing_pipe():
    backend = TmuxBackend(
        session_id=f"pipe-replace-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
    )
    backend._is_external = True

    calls: list[tuple] = []

    async def fake_run_tmux(*args, stdin_bytes=None, check=True):
        calls.append(args)
        if args[0] == "display-message":
            return 0, b"0|1|1000|0:0:0|/somewhere/else/theirs.pipe\n", b""
        return 0, b"", b""

    backend._run_tmux = fake_run_tmux  # type: ignore[assignment]

    asyncio.run(backend.ensure_pipe_pane())

    assert len(calls) == 4, (
        f"expected probe + close + start + record, got {len(calls)} "
        f"calls: {calls}"
    )
    assert calls[0][0] == "display-message", (
        f"first call must be display-message probe, got {calls[0][0]}"
    )

    assert calls[1][0] == "pipe-pane", (
        f"second call must close the existing pipe, got {calls[1]}"
    )
    assert len(calls[1]) == 3, (
        f"close call must carry no pipe command, got {calls[1]}"
    )

    assert calls[2][0] == "pipe-pane", (
        f"third call must start our pipe, got {calls[2]}"
    )
    assert calls[2][-1].startswith("cat >> "), (
        f"third call must pipe into our capture file, got {calls[2]}"
    )

    assert calls[3][0] == "set-option", (
        f"fourth call must record the owner on the pane, got {calls[3]}"
    )
    assert "-p" in calls[3], (
        f"the owner option must be a PANE option, got {calls[3]}"
    )
    assert PIPE_OWNER_OPTION in calls[3], (
        f"the owner option must be {PIPE_OWNER_OPTION}, got {calls[3]}"
    )
    assert calls[3][-1] == calls[2][-1][len("cat >> "):].strip("'\""), (
        f"the recorded path must be the path we piped into, got {calls[3]}"
    )


def test_ensure_pipe_pane_starts_pipe_when_not_active():
    backend = TmuxBackend(
        session_id=f"pipe-start-{uuid.uuid4().hex[:6]}",
        working_dir=Path.home(),
        on_output=None,
    )
    backend._is_external = True

    calls: list[tuple] = []

    async def fake_run_tmux(*args, stdin_bytes=None, check=True):
        calls.append(args)
        if args[0] == "display-message":
            return 0, b"0|0|1000|0:0:0|\n", b""
        return 0, b"", b""

    backend._run_tmux = fake_run_tmux  # type: ignore[assignment]

    asyncio.run(backend.ensure_pipe_pane())

    pipe_pane_calls = [c for c in calls if c and c[0] == "pipe-pane"]
    assert len(pipe_pane_calls) == 1, (
        f"expected exactly one pipe-pane call when pane_pipe=0, "
        f"got {len(pipe_pane_calls)}: {pipe_pane_calls}"
    )
    argv = pipe_pane_calls[0]
    assert "-o" not in argv, (
        f"pipe-pane must NOT use -o (toggle) when we've proven no pipe "
        f"is active; got argv {argv}"
    )
    option_calls = [c for c in calls if c and c[0] == "set-option"]
    assert len(option_calls) == 1 and PIPE_OWNER_OPTION in option_calls[0], (
        f"expected the owner option to be recorded once, got {option_calls}"
    )




def test_for_external_preserves_literal_name_without_slugify():
    literal = "my-literal-name"
    inst = TmuxBackend.for_external(
        session_name=literal,
        working_dir=Path("/tmp"),
        on_output=None,
    )

    assert inst.tmux_session == literal, (
        f"for_external must preserve literal name, got {inst.tmux_session!r}"
    )
    assert "cloude_" not in inst.tmux_session, (
        f"for_external must NOT prepend cloude_ prefix, got {inst.tmux_session!r}"
    )
    assert inst._is_external is True, (
        "for_external must flip _is_external=True so attach_existing takes "
        "the adopt branch (pipe-pane setup, remain-on-exit, window-size warn)"
    )
    assert inst.slug == literal


def test_for_external_rejects_unsafe_session_name():
    with pytest.raises(ValueError, match="unsafe tmux session name"):
        TmuxBackend.for_external(
            session_name="bad:name",
            working_dir=Path("/tmp"),
            on_output=None,
        )
    with pytest.raises(ValueError, match="unsafe tmux session name"):
        TmuxBackend.for_external(
            session_name="bad.name",
            working_dir=Path("/tmp"),
            on_output=None,
        )




@pytest.mark.asyncio
async def test_adopt_external_session_no_409_when_other_session_active():
    from src.core.session_manager import SessionManager
    from src.models import Session, SessionStatus

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    sess_a = Session(
        id="ses_existing",
        pty_pid=None,
        working_dir="/tmp",
        status=SessionStatus.RUNNING,
        created_at=datetime_for_tests(),
        last_activity=datetime_for_tests(),
    )
    backend_a = MagicMock()
    backend_a.is_alive = MagicMock(return_value=True)
    backend_a.tmux_session = "cloude_existing"
    sm._registry.register(sess_a, backend_a)

    sm._resolve_external_cwd = AsyncMock(return_value=Path("/tmp"))  # type: ignore[assignment]

    fake_backend = MagicMock()
    fake_backend.attach_existing = AsyncMock(return_value=None)
    fake_backend.capture_scrollback = MagicMock(return_value=b"")
    fake_backend.tmux_session = "external_target"
    fake_backend._pipe_path = Path("/tmp/does_not_exist_for_test.pipe")

    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external",
        return_value=fake_backend,
    ), patch(
        "src.core.session_manager.settings"
    ) as mock_settings:
        auth_cfg = MagicMock()
        auth_cfg.session.tmux_socket_name = _TEST_SOCKET
        auth_cfg.session.scrollback_lines = 3000
        mock_settings.load_auth_config.return_value = auth_cfg

        result = await sm.adopt_external_session(
            "external_target", confirm_detach=False
        )

    assert "session" in result and "initial_scrollback_b64" in result
    assert "fifo_start_offset" in result
    assert "ses_existing" in sm._registry.sessions, (
        "adopting a second session must NOT remove the first one"
    )
    assert "adopted:external_target" in sm._registry.sessions, (
        "the adopted session must be registered as a concurrent session"
    )
    fake_backend.attach_existing.assert_awaited_once()


@pytest.mark.asyncio
async def test_adopt_external_session_does_not_detach_or_destroy_prior():
    from src.core.session_manager import SessionManager
    from src.models import Session, SessionStatus

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    sess_a = Session(
        id="prior_session",
        pty_pid=None,
        working_dir="/tmp",
        status=SessionStatus.RUNNING,
        created_at=datetime_for_tests(),
        last_activity=datetime_for_tests(),
    )
    backend_a = MagicMock()
    backend_a.is_alive = MagicMock(return_value=True)
    backend_a.tmux_session = "cloude_prior"
    sm._registry.register(sess_a, backend_a)

    detach_mock = AsyncMock(return_value=True)
    sm.detach_current_session = detach_mock  # type: ignore[assignment]
    destroy_mock = AsyncMock(return_value=True)
    sm.destroy_session = destroy_mock  # type: ignore[assignment]
    sm._resolve_external_cwd = AsyncMock(return_value=Path("/tmp"))  # type: ignore[assignment]

    fake_backend = MagicMock()
    fake_backend.attach_existing = AsyncMock(return_value=None)
    fake_backend.capture_scrollback = MagicMock(return_value=b"")
    fake_backend.tmux_session = "external_target"
    fake_backend._pipe_path = Path("/tmp/does_not_exist_for_test.pipe")

    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external",
        return_value=fake_backend,
    ), patch(
        "src.core.session_manager.settings"
    ) as mock_settings:
        auth_cfg = MagicMock()
        auth_cfg.session.tmux_socket_name = _TEST_SOCKET
        auth_cfg.session.scrollback_lines = 3000
        mock_settings.load_auth_config.return_value = auth_cfg

        result = await sm.adopt_external_session(
            "external_target", confirm_detach=True
        )

    detach_mock.assert_not_awaited(), (
        "adopt must NOT detach the prior session — sessions are additive now"
    )
    destroy_mock.assert_not_awaited(), (
        "adopt must NEVER call destroy_session"
    )
    assert "session" in result
    fake_backend.attach_existing.assert_awaited_once()


def datetime_for_tests():
    from datetime import datetime
    return datetime.utcnow()




@pytest.mark.asyncio
async def test_concurrent_sessions_output_isolation():
    import base64

    from src.core.session_manager import SessionManager
    from src.models import Session, SessionStatus

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    def _mk_backend(name):
        b = MagicMock()
        b.is_alive = MagicMock(return_value=True)
        b.tmux_session = name

        async def _stop():
            return None

        b.stop = _stop
        return b

    sess_a = Session(id="ses_a", working_dir="/tmp", status=SessionStatus.RUNNING)
    sess_b = Session(id="ses_b", working_dir="/tmp", status=SessionStatus.RUNNING)
    sm._registry.register(sess_a, _mk_backend("cloude_a"))
    sm._registry.register(sess_b, _mk_backend("cloude_b"))

    qa = sm._registry.subscribe("ses_a")
    qb = sm._registry.subscribe("ses_b")

    assert not asyncio.iscoroutinefunction(sm._make_output_handler("ses_a"))

    handler_a = sm._make_output_handler("ses_a")
    handler_a(b"hello-A")

    assert qa.queued_items == 1, "session A's subscriber must receive A's bytes"
    got = base64.b64decode((await qa.get()).payload)
    assert got == b"hello-A"
    assert qb.queued_items == 0, "session B's subscriber must NOT receive A's bytes"

    handler_b = sm._make_output_handler("ses_b")
    handler_b(b"hello-B")
    assert qb.queued_items == 1
    assert base64.b64decode((await qb.get()).payload) == b"hello-B"
    assert qa.queued_items == 0

    metadata_path = sm.__class__.__module__  # noqa: F841
    with patch.object(type(sm), "_save_session_metadata", lambda *a, **k: None), \
         patch("src.core.session_manager.settings") as mock_settings:
        mock_settings.get_session_metadata_path.return_value = Path(
            "/tmp/never_existent_metadata_for_test.json"
        )
        await sm.destroy_session("ses_a")

    assert "ses_a" not in sm._registry.sessions
    assert "ses_b" in sm._registry.sessions, "destroying A must NOT remove B"
    assert qb in sm._registry.subscribers.get("ses_b", []), (
        "destroying A must not clear B's subscribers"
    )
    handler_b2 = sm._make_output_handler("ses_b")
    handler_b2(b"still-alive-B")
    assert base64.b64decode((await qb.get()).payload) == b"still-alive-B"




@pytest.mark.asyncio
async def test_adopt_external_session_reports_measured_dead_pane_as_gone():
    from src.core.session_adopt_persist import AdoptTargetGoneError
    from src.core.session_manager import SessionManager

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    sm.has_active_session = MagicMock(return_value=False)  # type: ignore[assignment]
    sm._resolve_external_cwd = AsyncMock(return_value=Path("/tmp"))  # type: ignore[assignment]

    fake_backend = MagicMock()
    fake_backend.attach_existing = AsyncMock(
        side_effect=PaneDeadError("cannot adopt foo: pane already dead")
    )
    fake_backend.capture_scrollback = MagicMock(return_value=b"")
    fake_backend._pipe_path = Path("/tmp/never_existent.pipe")

    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external",
        return_value=fake_backend,
    ), patch(
        "src.core.session_manager.settings"
    ) as mock_settings:
        auth_cfg = MagicMock()
        auth_cfg.session.tmux_socket_name = _TEST_SOCKET
        auth_cfg.session.scrollback_lines = 3000
        mock_settings.load_auth_config.return_value = auth_cfg

        with pytest.raises(AdoptTargetGoneError, match="pane already dead") as caught:
            await sm.adopt_external_session("foo", confirm_detach=True)
        assert type(caught.value) is not RuntimeError


@pytest.mark.asyncio
async def test_adopt_external_session_still_500s_when_the_probe_itself_fails():
    from src.core.session_adopt_persist import AdoptTargetGoneError
    from src.core.session_manager import SessionManager

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    sm.has_active_session = MagicMock(return_value=False)  # type: ignore[assignment]
    sm._resolve_external_cwd = AsyncMock(return_value=Path("/tmp"))  # type: ignore[assignment]

    fake_backend = MagicMock()
    fake_backend.attach_existing = AsyncMock(
        side_effect=RuntimeError("cannot adopt foo: pane-dead probe failed: timeout")
    )
    fake_backend.capture_scrollback = MagicMock(return_value=b"")
    fake_backend._pipe_path = Path("/tmp/never_existent.pipe")

    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external",
        return_value=fake_backend,
    ), patch(
        "src.core.session_manager.settings"
    ) as mock_settings:
        auth_cfg = MagicMock()
        auth_cfg.session.tmux_socket_name = _TEST_SOCKET
        auth_cfg.session.scrollback_lines = 3000
        mock_settings.load_auth_config.return_value = auth_cfg

        with pytest.raises(RuntimeError, match="probe failed") as caught:
            await sm.adopt_external_session("foo", confirm_detach=True)
        assert not isinstance(caught.value, AdoptTargetGoneError), (
            "an unmeasured probe failure must never be reported as gone"
        )




@pytest.mark.asyncio
async def test_lifespan_startup_does_not_rehydrate_non_owned_session(tmp_path):
    from src.core.session_manager import SessionManager
    from src.models import Session, SessionStatus

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    sm._registry.register(
        Session(
            id="foo",
            pty_pid=None,
            working_dir=str(tmp_path),
            status=SessionStatus.RUNNING,
            created_at=datetime_for_tests(),
            last_activity=datetime_for_tests(),
        ),
        backend=None,
    )
    sm._owned.names = set()
    sm._owned.needs_legacy_backfill = False

    fake_probe = MagicMock()
    fake_probe.discover_existing = MagicMock(return_value=["cloude_foo"])

    attach_mock = AsyncMock()
    fake_hydrate = MagicMock()
    fake_hydrate.tmux_session = "cloude_foo"
    fake_hydrate.attach_existing = attach_mock

    with patch(
        "src.core.session_manager.build_backend",
        side_effect=[fake_probe, fake_hydrate],
    ):
        sm._clear_stale_metadata = MagicMock(  # type: ignore[assignment]
            side_effect=lambda sid=None: sm._wipe_session_state(sid or "foo"),
        )
        await sm.lifespan_startup()

    attach_mock.assert_not_awaited()
    assert sm._registry.current_backend() is None, (
        "non-owned session must not be registered as an active backend"
    )


@pytest.mark.asyncio
async def test_lifespan_startup_legacy_backfill_populates_owned_set(tmp_path):
    from src.core.session_manager import SessionManager
    from src.models import Session, SessionStatus

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    sm._registry.register(
        Session(
            id="legacy_sess",
            pty_pid=None,
            working_dir=str(tmp_path),
            status=SessionStatus.RUNNING,
            created_at=datetime_for_tests(),
            last_activity=datetime_for_tests(),
        ),
        backend=None,
    )
    sm._owned.names = set()
    sm._owned.needs_legacy_backfill = True

    fake_probe = MagicMock()
    fake_probe.discover_existing = MagicMock(return_value=["cloude_legacy_sess"])

    attach_mock = AsyncMock()
    fake_hydrate = MagicMock()
    fake_hydrate.tmux_session = "cloude_legacy_sess"
    fake_hydrate.attach_existing = attach_mock

    save_mock = MagicMock()
    sm._save_session_metadata = save_mock  # type: ignore[assignment]

    with patch(
        "src.core.session_manager.build_backend",
        side_effect=[fake_probe, fake_hydrate],
    ):
        await sm.lifespan_startup()

    attach_mock.assert_awaited_once(), (
        "legacy-backfill path must still rehydrate the active session"
    )
    assert "cloude_legacy_sess" in sm._owned.names, (
        f"owned_tmux_sessions must be backfilled; got {sm._owned.names}"
    )
    save_mock.assert_called(), (
        "metadata must be re-persisted after legacy backfill to migrate schema"
    )




@requires_tmux
@pytest.mark.asyncio
async def test_adopt_external_session_end_to_end(tmp_path, monkeypatch):
    import base64

    from src.core.session_manager import SessionManager

    name = f"adopt_itest_{secrets.token_hex(4)}"
    marker = f"external-hello-{secrets.token_hex(3)}"
    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))

    subprocess.run(
        ["tmux", "-L", _TEST_SOCKET, "new-session", "-d", "-s", name],
        check=True,
        capture_output=True,
    )
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    try:
        subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "send-keys", "-t",
             name, f"echo {marker}", "Enter"],
            check=True,
            capture_output=True,
        )
        await asyncio.sleep(0.6)

        result = await sm.adopt_external_session(name, confirm_detach=True)

        assert "session" in result
        assert "initial_scrollback_b64" in result
        assert "fifo_start_offset" in result
        assert result["fifo_start_offset"] >= 0, (
            f"fifo_start_offset must be non-negative, got {result['fifo_start_offset']}"
        )

        sb_b64 = result["initial_scrollback_b64"]
        assert sb_b64, "initial_scrollback_b64 should be non-empty after the echo"
        decoded = base64.b64decode(sb_b64).decode("utf-8", "replace")
        assert marker in decoded, (
            f"expected marker {marker!r} in scrollback; got {decoded[:300]!r}..."
        )

        assert sm._registry.current_backend() is not None
        assert sm._registry.current_backend().tmux_session == name, (
            f"expected backend.tmux_session == {name!r}, "
            f"got {sm._registry.current_backend().tmux_session!r}"
        )

        second_marker = f"second-line-{secrets.token_hex(3)}"
        await sm._registry.current_backend().write(f"echo {second_marker}\n".encode("utf-8"))
        await asyncio.sleep(0.6)

        pane_bytes = sm._registry.current_backend().capture_scrollback()
        pane_text = pane_bytes.decode("utf-8", errors="replace")
        assert second_marker in pane_text, (
            f"second write must reach the pane; expected {second_marker!r}, "
            f"got trailing pane: {pane_text[-300:]!r}"
        )
    finally:
        subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "kill-session", "-t", name],
            check=False,
            capture_output=True,
        )
        if sm._registry.current_backend() is not None:
            try:
                await sm._registry.current_backend().stop()
            except Exception:
                pass




@requires_tmux
@pytest.mark.asyncio
async def test_detach_current_session_keeps_tmux_alive(tmp_path, monkeypatch):
    from src.core.session_manager import SessionManager

    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    session_id = f"detach_itest_{secrets.token_hex(4)}"

    try:
        await sm.create_session(
            session_id=session_id,
            working_dir=str(tmp_path),
            auto_start_claude=False,
        )
        assert sm._registry.current_backend() is not None
        tmux_name = sm._registry.current_backend().tmux_session
        assert tmux_name in sm._owned.names

        alive_before = subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "has-session", "-t", tmux_name],
            capture_output=True,
        )
        assert alive_before.returncode == 0, (
            "baseline: tmux session should be alive after create_session"
        )

        detached = await sm.detach_current_session()
        assert detached is True

        assert sm._registry.current_backend() is None, "detach must clear backend ref"
        assert sm._registry.current_session() is None, "detach must clear session ref"

        assert tmux_name in sm._owned.names, (
            "owned_tmux_sessions entry must survive detach so the Adopt "
            "UI labels the detached session as created_by_cloude=True"
        )

        alive_after = subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "has-session", "-t", tmux_name],
            capture_output=True,
        )
        assert alive_after.returncode == 0, (
            f"tmux session {tmux_name} must still be alive after detach "
            "(stderr: {!r})".format(alive_after.stderr.decode(errors='replace'))
        )

        assert await sm.detach_current_session() is False

    finally:
        subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "kill-session", "-t",
             f"cloude_{session_id}"],
            check=False,
            capture_output=True,
        )




@requires_tmux
@pytest.mark.asyncio
async def test_adopt_external_session_detach_keeps_prior_tmux_alive(
    tmp_path, monkeypatch
):
    from src.core.session_manager import SessionManager

    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    session_id_a = f"swap_prior_{secrets.token_hex(4)}"
    name_b = f"swap_ext_{secrets.token_hex(4)}"
    tmux_name_a: str | None = None

    try:
        await sm.create_session(
            session_id=session_id_a,
            working_dir=str(tmp_path),
            auto_start_claude=False,
        )
        assert sm._registry.current_backend() is not None, "A must be the active backend"
        tmux_name_a = sm._registry.current_backend().tmux_session
        assert tmux_name_a in sm._owned.names

        alive_a_before = subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "has-session", "-t", tmux_name_a],
            capture_output=True,
        )
        assert alive_a_before.returncode == 0, (
            "baseline: prior session A must be alive before adopt-swap"
        )

        subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "new-session", "-d", "-s", name_b],
            check=True,
            capture_output=True,
        )

        result = await sm.adopt_external_session(name_b, confirm_detach=True)
        assert "session" in result
        assert sm._registry.current_backend() is not None
        assert sm._registry.current_backend().tmux_session == name_b, (
            f"post-swap backend must point at B={name_b!r}, "
            f"got {sm._registry.current_backend().tmux_session!r}"
        )

        alive_a_after = subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "has-session", "-t", tmux_name_a],
            capture_output=True,
        )
        assert alive_a_after.returncode == 0, (
            f"prior session A={tmux_name_a!r} must still be alive after "
            "adopt-swap (detach-not-destroy); "
            f"stderr={alive_a_after.stderr.decode(errors='replace')!r}"
        )

        assert tmux_name_a in sm._owned.names, (
            "owned_tmux_sessions entry for A must survive adopt-swap "
            "so the launchpad re-lists A as cloude-owned"
        )

    finally:
        for tname in filter(None, [tmux_name_a, name_b]):
            subprocess.run(
                ["tmux", "-L", _TEST_SOCKET, "kill-session", "-t", tname],
                check=False,
                capture_output=True,
            )
        if sm._registry.current_backend() is not None:
            try:
                await sm._registry.current_backend().stop()
            except Exception:
                pass



def test_sanitize_tmux_name_preserves_verbatim_input():
    from src.core.session_name_claim import sanitize_tmux_name as _sanitize_tmux_name
    assert _sanitize_tmux_name("Cloude Code Dev") == "Cloude Code Dev"


def test_sanitize_tmux_name_replaces_dot_and_colon():
    from src.core.session_name_claim import sanitize_tmux_name as _sanitize_tmux_name
    assert _sanitize_tmux_name("Dotted.Name:Thing") == "Dotted_Name_Thing"


def test_sanitize_tmux_name_preserves_emoji_and_unicode():
    from src.core.session_name_claim import sanitize_tmux_name as _sanitize_tmux_name
    assert _sanitize_tmux_name("🔥 cool 🔥") == "🔥 cool 🔥"


def test_sanitize_tmux_name_collapses_whitespace_runs():
    from src.core.session_name_claim import sanitize_tmux_name as _sanitize_tmux_name
    assert _sanitize_tmux_name("   many   spaces   ") == "many spaces"


def test_sanitize_tmux_name_returns_empty_for_unusable_input():
    from src.core.session_name_claim import sanitize_tmux_name as _sanitize_tmux_name
    assert _sanitize_tmux_name("") == ""
    assert _sanitize_tmux_name("   ") == ""
    assert _sanitize_tmux_name(":::...") == "______"


def test_sanitize_tmux_name_only_separators_yields_underscore_run():
    from src.core.session_name_claim import sanitize_tmux_name as _sanitize_tmux_name
    assert _sanitize_tmux_name("...") == "___"


def test_sanitize_tmux_name_strips_newlines_and_tabs():
    from src.core.session_name_claim import sanitize_tmux_name as _sanitize_tmux_name
    assert _sanitize_tmux_name("foo\n\tbar") == "foo bar"


def test_tmux_backend_accepts_verbatim_session_name_override():
    backend = TmuxBackend(
        session_id="ses_abc123",
        working_dir=Path(tempfile.mkdtemp(prefix="cc_t2_")),
        session_name="cloude_Cloude Code Dev",
    )
    assert backend.tmux_session == "cloude_Cloude Code Dev"
    assert backend.session_id == "ses_abc123"


def test_tmux_backend_without_session_name_uses_legacy_slug():
    backend = TmuxBackend(
        session_id="ses_abc123",
        working_dir=Path(tempfile.mkdtemp(prefix="cc_t2b_")),
    )
    assert backend.tmux_session.startswith(TMUX_SESSION_PREFIX)
    assert "abc123" in backend.tmux_session


def test_create_session_request_accepts_project_name():
    from src.models import CreateSessionRequest
    req = CreateSessionRequest(
        working_dir="/tmp",
        auto_start_claude=False,
        copy_templates=False,
        project_name="Cloude Code Dev",
    )
    assert req.project_name == "Cloude Code Dev"


def test_create_session_request_project_name_defaults_to_none():
    from src.models import CreateSessionRequest
    req = CreateSessionRequest(
        working_dir="/tmp",
        auto_start_claude=False,
        copy_templates=False,
    )
    assert req.project_name is None




@requires_tmux
@pytest.mark.asyncio
async def test_session_manager_create_session_verbatim_name(tmp_path, monkeypatch):
    from src.core.session_manager import SessionManager

    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))

    session_id = f"t4verbatim_{secrets.token_hex(4)}"
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()
    try:
        await sm.create_session(
            session_id=session_id,
            working_dir=str(tmp_path),
            auto_start_claude=False,
            copy_templates=False,
            project_name="T4 Verbatim Test",
        )
        assert sm._registry.current_backend() is not None
        expected_tmux = f"{TMUX_SESSION_PREFIX}T4 Verbatim Test"
        assert sm._registry.current_backend().tmux_session == expected_tmux, (
            f"expected verbatim tmux_session {expected_tmux!r}, "
            f"got {sm._registry.current_backend().tmux_session!r}"
        )
    finally:
        if sm._registry.current_backend() is not None:
            try:
                await sm.destroy_session()
            except Exception:
                subprocess.run(
                    ["tmux", "-L", _TEST_SOCKET, "kill-session",
                     "-t", f"{TMUX_SESSION_PREFIX}T4 Verbatim Test"],
                    check=False,
                    capture_output=True,
                )


@requires_tmux
@pytest.mark.asyncio
async def test_session_manager_create_session_without_project_name_uses_legacy(
    tmp_path, monkeypatch
):
    from src.core.session_manager import SessionManager

    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))

    session_id = f"ses_{secrets.token_hex(4)}"
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()
    try:
        await sm.create_session(
            session_id=session_id,
            working_dir=str(tmp_path),
            auto_start_claude=False,
            copy_templates=False,
        )
        assert sm._registry.current_backend() is not None
        expected_prefix = f"{TMUX_SESSION_PREFIX}ses_"
        assert sm._registry.current_backend().tmux_session.startswith(
            expected_prefix
        ), (
            f"expected {expected_prefix}<hex> naming, "
            f"got {sm._registry.current_backend().tmux_session!r}"
        )
    finally:
        if sm._registry.current_backend() is not None:
            try:
                await sm.destroy_session()
            except Exception:
                pass




@requires_tmux
@pytest.mark.asyncio
async def test_create_session_uniquifies_when_target_name_exists(tmp_path, monkeypatch):
    from src.core.session_manager import SessionManager

    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))

    project_name = f"collide_{secrets.token_hex(4)}"
    target_tmux = f"{TMUX_SESSION_PREFIX}{project_name}"
    expected_new_tmux = f"{target_tmux}-2"

    subprocess.run(
        ["tmux", "-L", _TEST_SOCKET, "new-session", "-d", "-s", target_tmux],
        check=True,
    )
    try:
        wd = Path(tempfile.mkdtemp(prefix="cc_t5_"))
        with patch.object(SessionManager, "_load_session_metadata", return_value=None):
            sm = SessionManager()
        try:
            await sm.create_session(
                session_id=f"ses_{secrets.token_hex(4)}",
                working_dir=str(wd),
                auto_start_claude=False,
                copy_templates=False,
                project_name=project_name,
            )
            assert sm._registry.current_backend() is not None
            assert sm._registry.current_backend().tmux_session == expected_new_tmux, (
                f"expected uniquified tmux_session {expected_new_tmux!r}, "
                f"got {sm._registry.current_backend().tmux_session!r}"
            )
            assert subprocess.call(
                ["tmux", "-L", _TEST_SOCKET, "has-session", "-t", target_tmux],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ) == 0, "pre-existing tmux session was unexpectedly touched"
            assert subprocess.call(
                ["tmux", "-L", _TEST_SOCKET, "has-session", "-t", expected_new_tmux],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ) == 0, "new uniquified tmux session was not created"
        finally:
            if sm._registry.current_backend() is not None:
                try:
                    await sm.destroy_session()
                except Exception:
                    pass
    finally:
        subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "kill-session", "-t", target_tmux],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "-L", _TEST_SOCKET, "kill-session", "-t", expected_new_tmux],
            check=False,
            capture_output=True,
        )


@requires_tmux
@pytest.mark.asyncio
async def test_create_session_uniquifies_third_collision(tmp_path, monkeypatch):
    from src.core.session_manager import SessionManager

    monkeypatch.setenv("DEFAULT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))

    project_name = f"collide3_{secrets.token_hex(4)}"
    target_tmux = f"{TMUX_SESSION_PREFIX}{project_name}"
    second_tmux = f"{target_tmux}-2"
    expected_third_tmux = f"{target_tmux}-3"

    subprocess.run(
        ["tmux", "-L", _TEST_SOCKET, "new-session", "-d", "-s", target_tmux],
        check=True,
    )
    subprocess.run(
        ["tmux", "-L", _TEST_SOCKET, "new-session", "-d", "-s", second_tmux],
        check=True,
    )
    try:
        wd = Path(tempfile.mkdtemp(prefix="cc_t5c_"))
        with patch.object(SessionManager, "_load_session_metadata", return_value=None):
            sm = SessionManager()
        try:
            await sm.create_session(
                session_id=f"ses_{secrets.token_hex(4)}",
                working_dir=str(wd),
                auto_start_claude=False,
                copy_templates=False,
                project_name=project_name,
            )
            assert sm._registry.current_backend() is not None
            assert sm._registry.current_backend().tmux_session == expected_third_tmux, (
                f"expected uniquified tmux_session {expected_third_tmux!r}, "
                f"got {sm._registry.current_backend().tmux_session!r}"
            )
        finally:
            if sm._registry.current_backend() is not None:
                try:
                    await sm.destroy_session()
                except Exception:
                    pass
    finally:
        for name in (target_tmux, second_tmux, expected_third_tmux):
            subprocess.run(
                ["tmux", "-L", _TEST_SOCKET, "kill-session", "-t", name],
                check=False,
                capture_output=True,
            )


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))


def test_typed_text_and_keys_never_ride_on_argv(monkeypatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    backend = _make_backend_for_write_tests()
    _patch_run_tmux(backend)

    asyncio.run(backend.write(b"hunter2-secret"))
    asyncio.run(backend.write(b"\x03"))

    assert backend.raw_calls == [("source-file", "-"), ("source-file", "-")]
    assert not any("hunter2" in word for call in backend.raw_calls for word in call)


def test_newline_and_lone_semicolon_take_the_hex_path(monkeypatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "0")
    backend = _make_backend_for_write_tests()
    calls = _patch_run_tmux(backend)

    asyncio.run(backend.write(b"a\nb"))
    asyncio.run(backend.write(b";"))

    assert [c[1] for c in calls] == ["-H", "-H"]
