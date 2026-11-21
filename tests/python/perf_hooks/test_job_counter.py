
import asyncio
import json

from src.core.perf_hooks import call_counter, job_counter


def _pool_job_marker():
    return sum(range(1000))


async def _task_marker():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def _run(loop, with_window: bool):
    async def main():
        job_counter.attach(loop)
        try:
            if with_window:
                job_counter.reset()
                call_counter.start()
            await asyncio.gather(asyncio.to_thread(_pool_job_marker), asyncio.to_thread(_pool_job_marker),
                                 loop.create_task(_task_marker()))
        finally:
            rows = None
            if with_window:
                call_counter.stop(1.0)
                rows = job_counter.report(1.0)
            job_counter.detach(loop)
        return rows

    return loop.run_until_complete(main())


def test_window_names_pool_jobs_and_task_steps():
    loop = asyncio.new_event_loop()
    try:
        rows = _run(loop, True)
    finally:
        loop.close()
    jobs = {r["function"]: r for r in rows["executor_jobs"]}
    assert jobs[f"{__name__}._pool_job_marker"]["count"] == 2
    assert jobs[f"{__name__}._pool_job_marker"]["cpu_ms"] >= 0
    steps = {r["function"]: r for r in rows["loop_tasks"]}
    assert steps[f"{__file__.rsplit('/', 1)[-1]}:_task_marker"]["count"] == 3
    json.dumps(rows)


def test_nothing_recorded_outside_a_window():
    loop = asyncio.new_event_loop()
    try:
        _run(loop, False)
    finally:
        loop.close()
    assert job_counter.report(1.0) == {"executor_jobs": [], "loop_tasks": []}
