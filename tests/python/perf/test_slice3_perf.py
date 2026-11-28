
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import resize_negotiation, session_token_usage_routes, ws_startup_paint
from src.api.peer_auth import require_peer_sessions
from src.core.read_caches.ttl_flight import TtlFlight
from src.core.tmux_backend import TmuxBackend
from src.models.session_token_usage import SessionTokenUsage


def test_ttl_flight_coalesces_post_invalidation_callers_into_one_pass() -> None:
    async def go() -> None:
        cache: TtlFlight[list[str]] = TtlFlight("convoy_test", 60.0)
        gen0_entered = asyncio.Event()
        gen0_release = asyncio.Event()
        gen1_entered = asyncio.Event()
        gen1_release = asyncio.Event()
        calls = 0

        async def work() -> list[str]:
            nonlocal calls
            calls += 1
            mine = calls
            if mine == 1:
                gen0_entered.set()
                await gen0_release.wait()
                return ["old"]
            gen1_entered.set()
            await gen1_release.wait()
            return [f"fresh_{mine}"]

        t0 = asyncio.ensure_future(cache.get(work))
        await gen0_entered.wait()
        cache.invalidate()
        waiters = [asyncio.ensure_future(cache.get(work)) for _ in range(5)]
        await gen1_entered.wait()
        gen0_release.set()
        gen1_release.set()

        assert await t0 == ["old"]
        results = await asyncio.gather(*waiters)
        assert all(r == ["fresh_2"] for r in results)
        assert calls == 2

    asyncio.run(go())


def test_measured_size_frame_reuses_known_grid_without_tmux_probe() -> None:
    class _ForbiddenBackend:
        async def pane_geometry(self):
            raise AssertionError("should not probe tmux when known_grid is provided")

    frame = asyncio.run(resize_negotiation.measured_size_frame(_ForbiddenBackend(), known_grid=(140, 42)))
    assert frame is not None
    assert json.loads(frame) == {"type": "terminal_size", "cols": 140, "rows": 42, "measured": True}


def test_capture_attach_snapshot_combines_screen_alt_and_cursor() -> None:
    backend = object.__new__(TmuxBackend)
    backend.tmux_session = "cloude_snap"
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return 0, b"hello world\n<<<CARNIVORE_ATTACH_META>>> 0 5 2\n", b""

    backend._run_tmux_sync = fake_run  # type: ignore[method-assign]
    alt, screen = backend.capture_attach_snapshot()
    assert len(calls) == 1
    assert alt is False
    assert b"hello world" in screen
    assert b"\x1b[3;6H" in screen


def test_paint_on_attach_uses_pipelined_snapshot_when_available() -> None:
    sent_text: list[str] = []
    sent_bytes: list[bytes] = []

    class _WS:
        async def send_text(self, data: str) -> None:
            sent_text.append(data)

        async def send_bytes(self, data: bytes) -> None:
            sent_bytes.append(data)

    class _FastBackend:
        is_remote = False

        def capture_attach_snapshot(self):
            return False, b"prompt> "

        def pane_in_alternate_screen(self):
            raise AssertionError("must not call separate pane_in_alternate_screen")

        def capture_visible_screen(self):
            raise AssertionError("must not call separate capture_visible_screen")

    strategy = asyncio.run(ws_startup_paint.paint_on_attach(_WS(), _FastBackend()))
    assert strategy == "screen"
    assert json.loads(sent_text[0]) == {"type": "pane_screen", "alternate": False}
    assert sent_bytes[0].endswith(b"prompt> ")


def test_hydrate_sessions_batches_multiple_ids_via_resolve_session_ref(monkeypatch) -> None:
    refs = {
        "ses_1": {"session_id": "ses_1", "tmux_session": "t1", "working_dir": "/w1", "agent_family": "claude", "session_uuid": "u1", "claude_session_uuid": "c1", "tmux_created_epoch": 100},
        "ses_2": {"session_id": "ses_2", "tmux_session": "t2", "working_dir": "/w2", "agent_family": "claude", "session_uuid": "u2", "claude_session_uuid": "c2", "tmux_created_epoch": 200},
    }

    class _Mgr:
        async def resolve_session_ref(self, sid: str):
            return refs.get(sid)

        async def get_session_info(self, _sid: str):
            raise AssertionError("must use fast resolve_session_ref")

        def tmux_socket_name(self) -> str:
            return "cloude"

    async def fake_read(_mgr, sid: str, ref: dict) -> SessionTokenUsage:
        return SessionTokenUsage(state="ok", family="claude", model=f"model-{sid}", as_of="2026-11-22T00:00:00Z")

    monkeypatch.setattr(session_token_usage_routes, "_read_token_usage_for_ref", fake_read)
    monkeypatch.setattr(session_token_usage_routes, "remote_target", lambda _m, _s: None)

    app = FastAPI()
    app.include_router(session_token_usage_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_peer_sessions] = lambda: None
    app.state.session_manager = _Mgr()

    resp = TestClient(app).post("/api/v1/sessions/hydrate", json={"session_ids": ["ses_1", "ses_2", "missing", "ses_1"]})
    assert resp.status_code == 200
    body = resp.json()["token_usage"]
    assert set(body.keys()) == {"ses_1", "ses_2"}
    assert body["ses_1"]["model"] == "model-ses_1"
    assert body["ses_2"]["model"] == "model-ses_2"


def test_boot_readopt_session_for_stamps_tmux_created_epoch() -> None:
    from src.core.session_boot_readopt_plan import ReadoptTarget, session_for

    target = ReadoptTarget(
        name="carnivore_demo",
        epoch=1795483234,
        session_id="ses_demo",
        id_source="derived",
        working_dir="/tmp",
        agent_type="claude",
        via_fingerprint=False,
        origin="created",
    )
    sess = session_for(target)
    assert sess.tmux_created_epoch == 1795483234


def test_resolve_session_ref_uses_instance_epochs_for_session_uuid() -> None:
    from src.core.session_manager import SessionManager

    mgr = object.__new__(SessionManager)
    sess = SimpleNamespace(
        tmux_session="carnivore_work",
        working_dir="/tmp/work",
        tmux_created_epoch=None,
        agent_type="claude",
        agent_type_via_fingerprint=False,
    )
    backend = SimpleNamespace(tmux_session="carnivore_work")
    mgr._registry = SimpleNamespace(
        resolve_session_id=lambda sid: sid if sid == "ses_work" else None,
        sessions={"ses_work": sess},
        backends={"ses_work": backend},
    )
    mgr._instance_epochs = {"ses_work": 1795483234}
    mgr._ref_meta_cache = {}
    mgr._wrappers_reader = lambda: []
    seen: list[tuple[str, int | None]] = []

    def fake_read(tmux_name: str, epoch: int | None):
        seen.append((tmux_name, epoch))
        if epoch == 1795483234:
            return {
                "agent_family": "claude",
                "agent_type": "claude",
                "agent_family_source": "launch",
                "session_uuid": "00000000-0000-4000-8000-000000000003",
                "claude_session_uuid": "00000000-0000-4000-8000-000000000004",
                "tmux_created_epoch": 1795483234,
            }
        return None

    mgr._read_ref_db_row = fake_read  # type: ignore[method-assign]
    ref = asyncio.run(mgr.resolve_session_ref("ses_work"))
    assert ref is not None
    assert seen == [("carnivore_work", 1795483234)]
    assert ref["session_uuid"] == "00000000-0000-4000-8000-000000000003"
    assert ref["claude_session_uuid"] == "00000000-0000-4000-8000-000000000004"
    assert ref["tmux_created_epoch"] == 1795483234
