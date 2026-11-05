
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_emit_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_emit_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core import resource_push, session_change_notice  # noqa: E402
from src.core.app_alerts import service as alert_service  # noqa: E402
from src.core.db import db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.notifications import contracts, engine as eng, routing_view  # noqa: E402
from src.core.notifications.sources import alerts as alerts_source  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.models import Session, SessionStatus  # noqa: E402
from tests.python.notifications.engine_fakes import FakeSender, FakeView, FakeWriter, Screens, dest  # noqa: E402
from tests.python.notifications.test_sources_toast import _Settings  # noqa: E402

SESSION = "ses_a"


class LockedView(FakeView):

    def is_ticked(self, column: str, type_id: str) -> bool:
        from src.core.notifications import doc_model
        from src.core.notifications.settings_doc import view

        return not view.cell(doc_model.empty_doc(), column, type_id).locked


class EmitRig:

    def __init__(self, tmp_path: Path, monkeypatch: Any) -> None:
        self.tmp = tmp_path
        self.handled: List[contracts.NotifyEvent] = []
        self.frames: List[dict] = []
        self.bell: List[dict] = []
        self.session_frames: List[str] = []
        self.toasts: List[Any] = []
        self.sender = FakeSender()
        self.view = LockedView([dest(1, kind="webhook")])
        monkeypatch.setattr(session_change_notice, "publish", lambda _state, frame: self.frames.append(dict(frame)))
        monkeypatch.setattr(resource_push, "notify", lambda *a, **k: None)
        from src.api import websocket as ws_mod

        async def fan_out(_sid: str, payload: str) -> None:
            self.session_frames.append(payload)

        monkeypatch.setattr(ws_mod.connection_manager, "broadcast_to_session", fan_out)
        self.manager = self._manager(monkeypatch)
        self.app_state = SimpleNamespace(session_manager=self.manager)

    def _manager(self, monkeypatch: Any) -> SessionManager:
        (self.tmp / "logs").mkdir(exist_ok=True)
        monkeypatch.setattr("src.core.session_manager.settings", _Settings(self.tmp))
        manager = SessionManager()
        work = self.tmp / "proj"
        work.mkdir(exist_ok=True)
        manager._registry.sessions[SESSION] = Session(
            id=SESSION, pty_pid=None, working_dir=str(work), status=SessionStatus.RUNNING, tmux_session=None)
        manager._registry.subscribers.setdefault(SESSION, [])
        real = manager.record_toast

        def record_toast(*a: Any, **kw: Any) -> Any:
            toast = real(*a, **kw)
            self.toasts.append(toast)
            return toast

        manager.record_toast = record_toast
        return manager

    async def start(self) -> None:
        assert ensure_db_migrated(self.tmp).status == "ok"
        alert_service.configure(db_path_for(self.tmp), self.bell.append)
        alerts_source.install(asyncio.get_running_loop())

        async def secrets(_dest_id: str) -> dict:
            return {}

        self.engine = eng.NotifyEngine(
            sender_lookup=lambda kind: self.sender, is_muted=lambda sid: False, secrets_lookup=secrets,
            computer_name=lambda: "mini", screens=Screens(False), sms_state_dir=self.tmp)
        routing_view.install_routing(lambda: self.view, FakeWriter())
        real_handle = self.engine.handle

        async def handle(event: contracts.NotifyEvent) -> bool:
            self.handled.append(event)
            return await real_handle(event)

        self.engine.handle = handle
        await self.engine.start()
        eng.install_engine(self.engine)
        for module in {id(m): m for m in (contracts, sys.modules.get(contracts.__name__)) if m is not None}.values():
            module.install_sink(self.engine.offer)

    async def settle(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        for _ in range(3):
            await asyncio.sleep(0)
        while loop.time() < deadline and self.engine._tasks:
            await asyncio.sleep(0.01)
        await self.engine.join()

    async def stop(self) -> None:
        for module in {id(m): m for m in (contracts, sys.modules.get(contracts.__name__)) if m is not None}.values():
            module.uninstall_sink()
        await self.engine.stop()
        eng.install_engine(None)
        routing_view.uninstall_routing()
        alert_service.configure(None, None)

    def delivered(self, type_id: str) -> List[contracts.NotifyEvent]:
        return [call[0] for call in self.sender.calls if call[0].type_id == type_id]
