
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

from src.core.attention.evidence import REASON_PANE_DEAD, REASON_TURN_ENDED
from src.core.notifications import contracts
from src.core.notifications.sources import died
from src.core.notifications.sources.died import DiedTracker


def _obs(reason: str) -> Any:
    return SimpleNamespace(verdict=SimpleNamespace(reason=reason))


def _target(generation: Any = (1, 0), session_id: str = "ses_1") -> Any:
    return SimpleNamespace(session_id=session_id, key="cloude_api@7", generation=generation)


class _Rig:

    def __init__(self, monkeypatch) -> None:
        self.backend = SimpleNamespace()
        self.registry = SimpleNamespace(sessions={"ses_1": SimpleNamespace(tmux_session="cloude_api")},
                                        backends={"ses_1": self.backend})
        manager = SimpleNamespace(_registry=self.registry, _identity_for_live_name=lambda n: {"project_name": "api"},
                                  _label_for_tmux_name=lambda n: "API")
        self.events: List[contracts.NotifyEvent] = []
        self.frames: List[Any] = []
        monkeypatch.setattr(died.session_change_notice, "publish", lambda state, frame: self.frames.append(frame))
        self.tracker = DiedTracker(manager, object(), emit=self.events.append)


def test_fires_after_two_dead_reads_and_not_after_one(monkeypatch) -> None:
    rig = _Rig(monkeypatch)
    assert rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD)) is False and rig.events == []
    assert rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD)) is True
    event = rig.events[0]
    assert event.type_id == "session.died" and event.session_id == "ses_1" and event.project == "api"
    assert event.tmux_name == "cloude_api" and not event.open_item
    assert rig.frames == [{"type": "session.died", "session_id": "ses_1", "session_name": "API"}]


def test_fires_once_while_it_stays_dead_and_again_after_a_live_read(monkeypatch) -> None:
    rig = _Rig(monkeypatch)
    for _ in range(4):
        rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD))
    assert len(rig.events) == 1
    rig.tracker.observe(_target(), _obs(REASON_TURN_ENDED))
    rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD))
    rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD))
    assert len(rig.events) == 2


def test_a_live_read_between_two_dead_reads_resets_the_count(monkeypatch) -> None:
    rig = _Rig(monkeypatch)
    rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD))
    rig.tracker.observe(_target(), _obs(REASON_TURN_ENDED))
    rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD))
    assert rig.events == []


def test_never_fires_for_a_stop_the_manager_made(monkeypatch) -> None:
    rig = _Rig(monkeypatch)
    rig.backend._attention_stopping = True
    for _ in range(3):
        rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD))
    assert rig.events == [] and rig.frames == []


def test_never_fires_during_a_restart(monkeypatch) -> None:
    rig = _Rig(monkeypatch)
    rig.backend._attention_restarting = True
    for _ in range(3):
        rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD))
    assert rig.events == []


def test_a_restart_between_the_two_reads_starts_the_count_over(monkeypatch) -> None:
    rig = _Rig(monkeypatch)
    rig.tracker.observe(_target((1, 0)), _obs(REASON_PANE_DEAD))
    rig.tracker.observe(_target((1, 1)), _obs(REASON_PANE_DEAD))
    assert rig.events == []
    rig.tracker.observe(_target((1, 1)), _obs(REASON_PANE_DEAD))
    assert len(rig.events) == 1


def test_a_session_gone_from_the_registry_is_not_reported(monkeypatch) -> None:
    rig = _Rig(monkeypatch)
    rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD))
    del rig.registry.sessions["ses_1"]
    rig.tracker.observe(_target(), _obs(REASON_PANE_DEAD))
    assert rig.events == []


def test_tmux_backend_stop_marks_the_backend_so_the_tracker_can_tell(monkeypatch, tmp_path: Path) -> None:
    from src.core.tmux_backend import TmuxBackend

    backend = TmuxBackend("ses_1", tmp_path)
    backend._running = True

    async def no_tmux(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(backend, "_run_tmux", no_tmux)
    assert getattr(backend, "_attention_stopping", False) is False
    asyncio.run(backend.stop())
    assert backend._attention_stopping is True
