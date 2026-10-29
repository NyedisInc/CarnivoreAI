from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from tests.test_ws_subprotocol_auth import (  # noqa: F401
    _mint_token,
    patched_auth_config,
)

from tests.test_ws_handshake_paint import (
    PAINT_MARKER,
    SENTINEL_TYPE,
    _drive_handshake,
    _FakeLocalServers,
    _FakeLogMonitor,
    _PaintableBackend,
)

SESSION_ID = "ses_observer_probe"

LIVE_MARKER = b"CLOUDE-OBSERVER-STILL-STREAMING"

PAINT_BUDGET_SECONDS = 0.5

PRIMARY_COLS = 100
PRIMARY_ROWS = 30


class _RecordingManager:

    def __init__(self) -> None:
        self.viewed: list[str] = []
        self.inputs: list[str] = []
        self.resizes: list[tuple[int, int]] = []

    def mark_session_viewed(self, session_id: str) -> None:
        self.viewed.append(session_id)

    async def send_input(self, text, session_id=None) -> None:
        self.inputs.append(text)

    def resize_terminal(self, cols, rows, session_id=None) -> None:
        self.resizes.append((cols, rows))

    def capture_scrollback(self, lines=3000, session_id=None) -> bytes:
        return b""


class _FloodMonitor:

    class _Queue:

        async def get(self) -> str:
            return json.dumps({"type": "cloude.test.flood", "pad": "x" * 512})

    def subscribe(self):
        return self._Queue()

    def unsubscribe(self, q) -> None:
        pass

    def _detect_patterns(self, text) -> None:
        pass


def _build_app(log_monitor):
    from fastapi import FastAPI

    from src.api.websocket import router as ws_router
    from src.core.sessions.registry import SessionRegistry
    from src.models import Session

    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(
        Session(id=SESSION_ID, working_dir="/tmp"),
        _PaintableBackend(),
    )

    app = FastAPI()
    app.state.session_manager = _RecordingManager()
    app.state.services = SimpleNamespace(registry=registry)
    app.state.local_servers = _FakeLocalServers()
    app.state.log_monitor = log_monitor
    app.include_router(ws_router)
    return app


@pytest.fixture
def observer_app():
    return _build_app(_FakeLogMonitor())



def _url(observer: str | None = None, interactive: str | None = None) -> str:
    base = f"/ws/terminal?session_id={SESSION_ID}"
    if observer is not None:
        base = f"{base}&observer={observer}"
    if interactive is not None:
        base = f"{base}&interactive={interactive}"
    return base


def _connect(client, observer: str | None = None, interactive: str | None = None):
    return client.websocket_connect(
        _url(observer, interactive), subprotocols=["cloude.jwt.v1", _mint_token()]
    )


def _read_until_paint(ws, budget_frames: int = 40):
    from src.models import WSMessageType

    asked = False
    for _ in range(budget_frames):
        message = ws.receive()
        if message.get("bytes"):
            return message["bytes"], asked
        text = message.get("text")
        if not text:
            if message.get("type") == "websocket.close":
                return None, asked
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if parsed.get("type") == WSMessageType.REQUEST_DIMS:
            asked = True
        if parsed.get("type") == SENTINEL_TYPE:
            return None, asked
    return None, asked


def _record_negotiator(monkeypatch):
    from src.core.terminal_size import TerminalSizeNegotiator

    calls: dict[str, list] = {"set": [], "remove": []}
    real_set = TerminalSizeNegotiator.set_client_size
    real_remove = TerminalSizeNegotiator.remove_client

    def recording_set(self, session_id, client_key, cols, rows, voting=True):
        calls["set"].append((session_id, id(client_key), cols, rows))
        return real_set(self, session_id, client_key, cols, rows, voting=voting)

    def recording_remove(self, session_id, client_key):
        calls["remove"].append((session_id, id(client_key)))
        return real_remove(self, session_id, client_key)

    monkeypatch.setattr(
        TerminalSizeNegotiator, "set_client_size", recording_set)
    monkeypatch.setattr(
        TerminalSizeNegotiator, "remove_client", recording_remove)
    return calls


def _effective(app):
    from src.api.resize_negotiation import get_negotiator

    return get_negotiator(app.state.session_manager).effective_size(SESSION_ID)




def test_an_observer_never_enters_the_size_negotiator(observer_app, monkeypatch):
    from fastapi.testclient import TestClient

    calls = _record_negotiator(monkeypatch)
    client = TestClient(observer_app)

    with _connect(client) as primary:
        painted = _drive_handshake(primary, cols=PRIMARY_COLS, rows=PRIMARY_ROWS)
        assert painted is not None, "the primary never attached; fixture broken"
        before = _effective(observer_app)
        assert before == (PRIMARY_COLS, PRIMARY_ROWS), (
            "the control never reached the negotiator, so every assertion "
            f"below measures nothing. effective={before!r}"
        )

        with _connect(client, "1") as observer:
            observer_painted, asked = _read_until_paint(observer)
            assert observer_painted is not None, "the observer never painted"
            observer.send_text(json.dumps({
                "type": "pty_resize", "cols": 20, "rows": 5,
            }))
            observer_app.state.services.registry.publish(SESSION_ID, LIVE_MARKER)
            _read_until_paint(observer)
            assert _effective(observer_app) == before, (
                "the observer's pty_resize reached the negotiator and "
                "letterboxed the pane under the live terminal"
            )

        after = _effective(observer_app)

    assert after == before, (
        "the observer's DISCONNECT moved the negotiated size, which means "
        "release_client_resize ran for a socket that never registered"
    )
    assert len(calls["set"]) == 1, (
        "set_client_size was called once per attaching client; an observer "
        f"must call it zero times. calls={calls['set']!r}"
    )
    assert len(calls["remove"]) == 1, (
        "remove_client ran for a socket that never entered the negotiator. "
        f"calls={calls['remove']!r}"
    )


def test_a_primary_attaching_hidden_never_votes_not_even_once(observer_app):
    from fastapi.testclient import TestClient
    from src.models import WSMessageType

    client = TestClient(observer_app)
    with _connect(client) as primary:
        assert _drive_handshake(
            primary, cols=PRIMARY_COLS, rows=PRIMARY_ROWS) is not None
        assert _effective(observer_app) == (PRIMARY_COLS, PRIMARY_ROWS)

        with _connect(client) as background:
            for _ in range(40):
                text = background.receive().get("text")
                if text and json.loads(text).get("type") == WSMessageType.REQUEST_DIMS:
                    break
            background.send_text(json.dumps({
                "type": "pty_resize", "cols": 20, "rows": 5, "hidden": True,
            }))
            painted, _asked = _read_until_paint(background)
            assert painted is not None, "the hidden tab never attached"
            assert _effective(observer_app) == (PRIMARY_COLS, PRIMARY_ROWS), (
                "a tab that attached hidden voted in its handshake"
            )

            background.send_text(json.dumps({
                "type": "pty_resize", "cols": 20, "rows": 5,
            }))
            observer_app.state.services.registry.publish(SESSION_ID, LIVE_MARKER)
            _read_until_paint(background)
            assert _effective(observer_app) == (20, 5), (
                "the control failed: a visible resize from the same socket "
                "did not reach the negotiator, so the assertion above "
                "measured nothing"
            )




def test_an_observer_paints_immediately_and_is_never_asked_for_dims(observer_app):
    from fastapi.testclient import TestClient

    client = TestClient(observer_app)

    started = time.monotonic()
    with _connect(client, "1") as ws:
        painted, asked = _read_until_paint(ws)
        elapsed = time.monotonic() - started

    assert painted is not None and PAINT_MARKER in painted, (
        f"the observer's attach never painted the pane: {painted!r}"
    )
    assert not asked, (
        "the server asked a read-only socket for its dimensions; answering "
        "would put it in the negotiator and never answering costs it the "
        "full handshake deadline"
    )
    assert elapsed < PAINT_BUDGET_SECONDS, (
        f"the observer waited {elapsed:.2f}s for its paint, over the "
        f"{PAINT_BUDGET_SECONDS}s budget: it is sitting in the handshake "
        "deadline it is supposed to skip"
    )




def test_an_observer_does_not_clear_the_unread_flag(observer_app):
    from fastapi.testclient import TestClient

    client = TestClient(observer_app)
    manager = observer_app.state.session_manager

    with _connect(client, "1") as ws:
        _read_until_paint(ws)
    assert manager.viewed == [], (
        "an observer cleared the session's unread flag; every session a "
        "dashboard shows would silently stop asking for attention"
    )

    with _connect(client) as primary:
        _drive_handshake(primary, cols=PRIMARY_COLS, rows=PRIMARY_ROWS)
    assert manager.viewed == [SESSION_ID], (
        "THE CONTROL FAILED: a normal terminal socket no longer clears the "
        "unread flag either, so the assertion above proves nothing about "
        f"the observer. viewed={manager.viewed!r}"
    )




def test_an_observer_input_frame_is_dropped_logged_and_survivable(observer_app):
    import structlog
    from fastapi.testclient import TestClient

    from src.api import terminal_socket_role as socket_role

    client = TestClient(observer_app)
    manager = observer_app.state.session_manager
    registry = observer_app.state.services.registry
    typed = "rm -rf /\r"

    with structlog.testing.capture_logs() as captured:
        with _connect(client, "1") as ws:
            painted, _asked = _read_until_paint(ws)
            assert painted is not None, "the observer never attached"

            ws.send_bytes(typed.encode())
            ws.send_text(json.dumps({
                "type": "pty_resize", "cols": 20, "rows": 5,
            }))

            registry.publish(SESSION_ID, LIVE_MARKER)
            live, _ = _read_until_paint(ws)

    assert live is not None and LIVE_MARKER in live, (
        "the socket stopped delivering output after a refused frame: the "
        "refusal closed or wedged the connection instead of dropping one "
        f"frame. got {live!r}"
    )
    assert manager.inputs == [], (
        f"a read-only socket wrote to the pane: {manager.inputs!r}"
    )

    refusals = [
        entry for entry in captured
        if entry.get("event") == socket_role.OBSERVER_REFUSAL_EVENT
    ]
    assert refusals, (
        "the frames were dropped silently; a drop nobody can see is "
        f"indistinguishable from a socket that stopped reading: {captured!r}"
    )
    reasons = {entry.get("reason") for entry in refusals}
    assert reasons == {
        socket_role.REASON_BINARY_INPUT,
        socket_role.REASON_PTY_RESIZE,
    }, (
        f"the two frame kinds were not both refused by name: {reasons!r}"
    )
    assert all(
        entry.get("session_id") == SESSION_ID for entry in refusals
    ), f"a refusal did not say which session it was on: {refusals!r}"
    assert not any(
        typed in str(value) for entry in refusals for value in entry.values()
    ), (
        "THE PAYLOAD WAS LOGGED. A terminal input frame is whatever the "
        f"user typed, which is as likely to be a token as a command: "
        f"{refusals!r}"
    )




def test_an_observer_is_still_bounded_and_closed_with_4429(monkeypatch):
    from fastapi.testclient import TestClient

    from src.core import viewer_fanout

    monkeypatch.setattr(viewer_fanout, "MAX_VIEWER_QUEUE_CHUNKS", 1)
    monkeypatch.setattr(viewer_fanout, "MAX_VIEWER_QUEUE_BYTES", 64)

    app = _build_app(_FloodMonitor())
    client = TestClient(app)

    code = None
    with _connect(client, "1") as ws:
        for _ in range(64):
            message = ws.receive()
            if message.get("type") == "websocket.close":
                code = message.get("code")
                break

    assert code == 4429, (
        f"an observer that fell behind was closed with {code!r}, not the "
        "4429 the client recovers from without a reconnect banner"
    )
    assert viewer_fanout.VIEWER_OVERFLOW_CLOSE_CODE == 4429, (
        "the endpoint and this test now disagree about the overflow code"
    )




@pytest.mark.parametrize(
    "raw,expected_observer",
    [
        ("1", True),
        ("0", False),
        ("", False),
        ("true", False),
        ("yes", False),
        ("01", False),
        ("1 ", False),
        ("2", False),
        (None, False),
    ],
)
def test_only_the_exact_flag_selects_the_observer_role(raw, expected_observer):
    from src.api import terminal_socket_role as socket_role

    params = {} if raw is None else {socket_role.OBSERVER_QUERY_PARAM: raw}
    role = socket_role.role_for_query(params)

    if expected_observer:
        assert role is socket_role.OBSERVER_ROLE
        assert not any((
            role.negotiates_size,
            role.awaits_handshake,
            role.marks_viewed,
            role.accepts_input,
        ))
    else:
        assert role is socket_role.PRIMARY_ROLE
        assert all((
            role.negotiates_size,
            role.awaits_handshake,
            role.marks_viewed,
            role.accepts_input,
        ))


def test_the_role_is_frozen_so_the_read_loop_cannot_widen_it():
    import dataclasses

    from src.api import terminal_socket_role as socket_role

    with pytest.raises(dataclasses.FrozenInstanceError):
        socket_role.OBSERVER_ROLE.accepts_input = True


def test_an_absent_query_string_is_a_primary():
    from src.api import terminal_socket_role as socket_role

    assert socket_role.role_for_query(None) is socket_role.PRIMARY_ROLE




class _MeasuredBackend(_PaintableBackend):

    def __init__(self, cols: int = 143, rows: int = 41) -> None:
        super().__init__()
        self._geometry = (cols, rows)

    async def pane_geometry(self):
        return self._geometry


class _UnmeasurableBackend(_PaintableBackend):

    async def pane_geometry(self):
        return None


def _app_with(backend):
    from fastapi import FastAPI

    from src.api.websocket import router as ws_router
    from src.core.sessions.registry import SessionRegistry
    from src.models import Session

    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(Session(id=SESSION_ID, working_dir="/tmp"), backend)

    app = FastAPI()
    app.state.session_manager = _RecordingManager()
    app.state.services = SimpleNamespace(registry=registry)
    app.state.local_servers = _FakeLocalServers()
    app.state.log_monitor = _FakeLogMonitor()
    app.include_router(ws_router)
    return app


def _read_size_then_paint(ws, budget_frames: int = 40):
    size = None
    for _ in range(budget_frames):
        message = ws.receive()
        if message.get("bytes"):
            return size, message["bytes"]
        text = message.get("text")
        if not text:
            if message.get("type") == "websocket.close":
                return size, None
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if parsed.get("type") == "terminal_size" and size is None:
            size = parsed
        if parsed.get("type") == SENTINEL_TYPE:
            return size, None
    return size, None


def test_an_observer_is_told_the_panes_grid_before_it_is_painted():
    from fastapi.testclient import TestClient

    app = _app_with(_MeasuredBackend(143, 41))
    client = TestClient(app)

    with _connect(client, "1") as ws:
        size, painted = _read_size_then_paint(ws)

    assert size is not None, (
        "the observer was painted without ever being told the pane's grid, "
        "so it can only guess at the width of the screen it is drawing"
    )
    assert (size.get("cols"), size.get("rows")) == (143, 41), (
        f"the grid the observer was told is not the pane's: {size!r}"
    )
    assert painted is not None and PAINT_MARKER in painted, (
        f"the observer's attach never painted the pane: {painted!r}"
    )


def test_a_pane_that_cannot_be_measured_states_no_grid_at_all():
    from fastapi.testclient import TestClient

    app = _app_with(_UnmeasurableBackend())
    client = TestClient(app)

    with _connect(client, "1") as ws:
        size, painted = _read_size_then_paint(ws)

    assert size is None, (
        f"an unreadable pane produced a grid claim anyway: {size!r}"
    )
    assert painted is not None and PAINT_MARKER in painted, (
        "withholding the grid cost the observer its paint"
    )


def _drive_primary(ws, seen: list, budget_frames: int = 40):
    from src.models import WSMessageType

    answered = False
    painted = None
    for _ in range(budget_frames):
        message = ws.receive()
        if message.get("bytes"):
            if painted is None:
                painted = message["bytes"]
            continue
        text = message.get("text")
        if not text:
            if message.get("type") == "websocket.close":
                return painted
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        seen.append(parsed)
        if parsed.get("type") == WSMessageType.REQUEST_DIMS and not answered:
            answered = True
            ws.send_text(json.dumps({
                "type": WSMessageType.PTY_RESIZE, "cols": 120, "rows": 30,
            }))
        if parsed.get("type") == WSMessageType.TERMINAL_READY:
            return painted
        if parsed.get("type") == SENTINEL_TYPE:
            return painted
    return painted


def test_a_primary_is_never_sent_the_observer_grid_frame():
    from fastapi.testclient import TestClient

    app = _app_with(_MeasuredBackend(143, 41))
    client = TestClient(app)

    seen: list = []
    with _connect(client, None) as ws:
        painted = _drive_primary(ws, seen)

    sizes = [frame for frame in seen if frame.get("type") == "terminal_size"]
    assert sizes == [], (
        f"a primary was handed the observer's grid frame: {sizes!r}"
    )
    assert painted is not None, "the primary's own attach never painted"




def test_an_interactive_viewer_types_into_the_pane(observer_app):
    import structlog
    from fastapi.testclient import TestClient

    from src.api import terminal_socket_role as socket_role

    client = TestClient(observer_app)
    manager = observer_app.state.session_manager
    typed = "echo hello\r"

    with structlog.testing.capture_logs() as captured:
        with _connect(client, "1", "1") as ws:
            painted, asked = _read_until_paint(ws)
            assert painted is not None, "the interactive viewer never attached"
            assert not asked, (
                "the interactive viewer was asked for its dimensions: it "
                "sends none, so the two second wait buys a blank cell"
            )
            ws.send_bytes(typed.encode())
            registry = observer_app.state.services.registry
            registry.publish(SESSION_ID, LIVE_MARKER)
            live, _ = _read_until_paint(ws)

    assert live is not None and LIVE_MARKER in live, (
        f"the socket stopped delivering output after the input: {live!r}"
    )
    assert manager.inputs == [typed], (
        "the user's keystrokes never reached the pane, so the cell is a "
        f"terminal that cannot be typed into: {manager.inputs!r}"
    )
    refusals = [
        entry for entry in captured
        if entry.get("event") == socket_role.OBSERVER_REFUSAL_EVENT
    ]
    assert refusals == [], (
        "the input was accepted AND logged as refused, which means one of "
        f"the two gates still reads the wrong capability: {refusals!r}"
    )

    manager.inputs.clear()
    with _connect(client, "1") as readonly:
        assert _read_until_paint(readonly)[0] is not None
        readonly.send_bytes(typed.encode())
        observer_app.state.services.registry.publish(SESSION_ID, LIVE_MARKER)
        _read_until_paint(readonly)
    assert manager.inputs == [], (
        "THE CONTROL FAILED: a plain observer now writes to the pane too, "
        "so the assertion above proves nothing about the flag. "
        f"inputs={manager.inputs!r}"
    )


def test_an_interactive_viewer_still_never_enters_the_size_negotiator(
        observer_app, monkeypatch):
    from fastapi.testclient import TestClient

    calls = _record_negotiator(monkeypatch)
    client = TestClient(observer_app)

    with _connect(client) as primary:
        _drive_handshake(primary, cols=PRIMARY_COLS, rows=PRIMARY_ROWS)
        before = _effective(observer_app)
        assert before == (PRIMARY_COLS, PRIMARY_ROWS), (
            f"the control never established a size: {before!r}"
        )
        assert calls["set"], (
            "THE RECORDER SAW NOTHING for a real client, so the emptiness "
            "asserted below would be an artefact of the recorder"
        )
        primary_sets = len(calls["set"])

        with _connect(client, "1", "1") as cell:
            assert _read_until_paint(cell)[0] is not None
            cell.send_text(json.dumps({
                "type": "pty_resize", "cols": 20, "rows": 5,
            }))
            cell.send_bytes(b"x")
            observer_app.state.services.registry.publish(
                SESSION_ID, LIVE_MARKER)
            assert _read_until_paint(cell)[0] is not None
            during = _effective(observer_app)

        after = _effective(observer_app)

    assert during == (PRIMARY_COLS, PRIMARY_ROWS), (
        "a terminal cell the user can type into shrank the shared pane "
        f"under the real terminal: {during!r}"
    )
    assert after == (PRIMARY_COLS, PRIMARY_ROWS), f"{after!r}"
    assert len(calls["set"]) == primary_sets, (
        "the interactive cell reached the negotiator: "
        f"{calls['set']!r}"
    )


def test_an_interactive_viewer_does_not_clear_the_unread_flag(observer_app):
    from fastapi.testclient import TestClient

    client = TestClient(observer_app)
    manager = observer_app.state.session_manager

    with _connect(client, "1", "1") as ws:
        _read_until_paint(ws)
    assert manager.viewed == [], (
        "an interactive cell cleared the session's unread flag; a surface "
        "of six cells would silence six sessions the user never opened"
    )

    with _connect(client) as primary:
        _drive_handshake(primary, cols=PRIMARY_COLS, rows=PRIMARY_ROWS)
    assert manager.viewed == [SESSION_ID], (
        "THE CONTROL FAILED: a normal terminal socket no longer clears the "
        f"flag either. viewed={manager.viewed!r}"
    )


@pytest.mark.parametrize(
    "observer,interactive,expected",
    [
        ("1", "1", "interactive"),
        ("1", None, "observer"),
        ("1", "0", "observer"),
        ("1", "true", "observer"),
        ("1", "", "observer"),
        (None, "1", "primary"),
        ("0", "1", "primary"),
        (None, None, "primary"),
    ],
)
def test_interactive_is_read_only_alongside_observer(
        observer, interactive, expected):
    from src.api import terminal_socket_role as socket_role

    params = {}
    if observer is not None:
        params[socket_role.OBSERVER_QUERY_PARAM] = observer
    if interactive is not None:
        params[socket_role.INTERACTIVE_QUERY_PARAM] = interactive

    role = socket_role.role_for_query(params)

    if expected == "interactive":
        assert role is socket_role.INTERACTIVE_VIEWER_ROLE
        assert role.accepts_input
        assert not role.negotiates_size
        assert not role.awaits_handshake
        assert not role.marks_viewed
    elif expected == "observer":
        assert role is socket_role.OBSERVER_ROLE
    else:
        assert role is socket_role.PRIMARY_ROLE




def test_the_two_surfaces_ask_for_two_different_roles():
    from src.api.terminal_socket_role import (
        INTERACTIVE_VIEWER_ROLE,
        PRIMARY_ROLE,
        role_for_query,
    )

    terminal_cell = role_for_query({})
    assert terminal_cell is PRIMARY_ROLE
    assert terminal_cell.negotiates_size is True, (
        "a terminal-page cell must vote in its own session's grid"
    )
    assert terminal_cell.accepts_input is True

    home_cell = role_for_query({"observer": "1", "interactive": "1"})
    assert home_cell is INTERACTIVE_VIEWER_ROLE
    assert home_cell.accepts_input is True, "a home cell still takes typing"
    assert home_cell.negotiates_size is False, (
        "a home cell voted on the grid of a session driven elsewhere"
    )
    assert home_cell.awaits_handshake is False
    assert home_cell.marks_viewed is False

    assert terminal_cell != home_cell
