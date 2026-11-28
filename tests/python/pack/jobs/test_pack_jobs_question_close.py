
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.core.pack.jobs import agent_watch
from src.core.pack.jobs.agent_watch import AgentWatch, Look, Read
from src.core.pack.jobs.types import HostState


def _watch(read: Read, ended: list, parked: list, clock: list) -> AgentWatch:
    row = SimpleNamespace(job_id="job_x", state=HostState.RUNNING, body="agent", started_at=1.0, time_cap_s=10**9, worker_session_id="ses_1",
                          replied_at=None, parked_at=None, question_kind=None, question=None)
    store = SimpleNamespace(host_get=lambda _j: row, host_set=lambda *_a, **_k: None)

    async def result(_row): return read
    async def usage(_row): return None
    async def park(_row, kind, text): parked.append((kind, text))
    async def unpark(_row): return None
    async def finish(_row, ending, text): ended.append(ending); row.state = HostState.EXITED
    async def sleep(_s):
        clock[0] += 60.0
        await asyncio.sleep(0)

    return AgentWatch(store=store, observe=lambda _s: None, read_result=result, read_usage=usage, park=park, unpark=unpark, finish=finish,
                      floor=lambda _j: 100.0, busy_replying=lambda _j: False, clock=lambda: clock[0], sleep=sleep)


def test_a_worker_ending_on_a_question_parks_and_a_stale_transcript_still_ends(monkeypatch) -> None:
    monkeypatch.setattr(agent_watch, "classify", lambda _o: Look("finished"))
    parked: list = []
    ended: list = []
    clock = [1000.0]
    asked = Read("options:\n❓ which one?", 50.0)
    watch = _watch(asked, ended, parked, clock)
    async def drive() -> None:
        task = asyncio.create_task(watch.run("job_x"))
        await asyncio.sleep(0.2)
        task.cancel()
    asyncio.run(drive())
    assert parked and parked[0][0] == "question" and "which one" in parked[0][1]
    assert not ended

    plain, ended2, parked2, clock2 = Read("all done", 50.0), [], [], [1000.0]
    asyncio.run(asyncio.wait_for(_watch(plain, ended2, parked2, clock2).run("job_x"), 5))
    assert ended2 and ended2[0].code == 0 and not parked2
