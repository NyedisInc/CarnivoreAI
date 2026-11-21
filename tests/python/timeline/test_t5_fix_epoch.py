
from __future__ import annotations

from typing import Any, Dict, List

from src.core.timeline import push
from tests.python.timeline.exposure_helpers import CONV, Clock, append, step, turn


def _coalescer() -> tuple:
    sent: List[Dict[str, Any]] = []
    clock = Clock()
    return push.FrameCoalescer(lambda frame: sent.append(frame) or True, clock.now, clock.later), sent, clock


def _add(coalescer: Any, session: str, offset: int) -> None:
    coalescer.add(session, "c", "main", (offset, "s"), {}, None)


def test_n5_frames_of_one_run_share_an_epoch_and_a_restart_of_seq_changes_it() -> None:
    coalescer, sent, clock = _coalescer()
    _add(coalescer, "s1", 1)
    clock.advance(2.0)
    _add(coalescer, "s1", 2)
    assert [f["seq"] for f in sent] == [1, 2] and sent[0]["epoch"] == sent[1]["epoch"] and sent[0]["epoch"]
    coalescer.clear()
    clock.advance(2.0)
    _add(coalescer, "s1", 3)
    assert sent[2]["seq"] == 1 and sent[2]["epoch"] != sent[0]["epoch"]


def test_n5_an_evicted_session_restarts_under_a_new_epoch(monkeypatch) -> None:
    monkeypatch.setattr(push, "MAX_REMEMBERED", 2)
    coalescer, sent, clock = _coalescer()
    for name in ("s1", "s2", "s3"):
        _add(coalescer, name, 1)
        clock.advance(2.0)
    _add(coalescer, "s1", 2)
    assert sent[-1]["seq"] == 1 and sent[-1]["epoch"] != sent[0]["epoch"]
    assert coalescer.epoch_of("s1") == sent[-1]["epoch"]


def test_n5_the_state_route_answers_the_epoch_the_next_frame_carries(api, frames, switch) -> None:
    client, main = api
    sent, clock = frames
    append(main, turn(0, "a"))
    step(main)
    first = client.get("/api/v1/sessions/ses_1/timeline/state").json()
    assert first["epoch"] == sent[-1]["epoch"] and first["seq"] == sent[-1]["seq"] == 1
    clock.advance(2.0)
    append(main, turn(10, "b"))
    step(main)
    clock.advance(2.0)
    assert sent[-1]["epoch"] == first["epoch"] and sent[-1]["seq"] == 2
    assert client.get("/api/v1/sessions/ses_1/timeline/state").json()["epoch"] == first["epoch"]


def test_epoch_of_from_a_thread_never_splits_the_epoch_a_frame_carries() -> None:
    import threading
    from collections import OrderedDict

    coalescer, _sent, _clock = _coalescer()
    coalescer._next_seq("s1")
    seen: List[Dict[str, Any]] = []
    racer = threading.Thread(target=lambda: seen.append(coalescer._next_seq("s1")), daemon=True)

    class Hooked(OrderedDict):

        fired = False

        def pop(self, key: Any, *default: Any) -> Any:
            entry = super().pop(key, *default)
            if not self.fired:
                self.fired = True
                racer.start()
                racer.join(0.3)
            return entry

    hooked = Hooked(coalescer._seq)
    coalescer._seq = hooked
    answered = coalescer.epoch_of("s1")
    racer.join(5)
    assert seen and seen[0]["epoch"] == answered == coalescer.epoch_of("s1"), f"epoch split: answered {answered}, frame {seen}"
