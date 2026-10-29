import asyncio
import threading
import time

import pytest

from src.core.work_admission import AdmissionRefused, Admission, WorkClass


def _blocker():
    gate = threading.Event()
    return gate, lambda: gate.wait(5)


@pytest.mark.asyncio
async def test_saturated_background_never_delays_interactive_or_reconcile():
    adm = Admission()
    gate, work = _blocker()
    jobs = [asyncio.create_task(adm.run(WorkClass.BACKGROUND, work)) for _ in range(5)]
    jobs += [asyncio.create_task(adm.run(WorkClass.BULK_SCAN, work)) for _ in range(2)]
    await asyncio.sleep(0.05)
    assert adm.in_flight(WorkClass.BACKGROUND) == adm.limit(WorkClass.BACKGROUND)
    start = time.monotonic()
    p = await asyncio.wait_for(adm.acquire(WorkClass.INTERACTIVE), 0.2)
    assert await adm.run(WorkClass.RECONCILE, lambda: "ok", timeout=0.5) == "ok"
    p.release()
    assert time.monotonic() - start < 0.5
    gate.set()
    await asyncio.gather(*jobs)


@pytest.mark.asyncio
async def test_cancelled_request_keeps_its_permit_until_the_work_returns():
    adm = Admission({WorkClass.BULK_SCAN: 1})
    gate, work = _blocker()
    request = asyncio.create_task(adm.run(WorkClass.BULK_SCAN, work))
    await asyncio.sleep(0.05)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert adm.in_flight(WorkClass.BULK_SCAN) == 1
    with pytest.raises(AdmissionRefused):
        await adm.run(WorkClass.BULK_SCAN, lambda: None, timeout=0.1)
    gate.set()
    for _ in range(100):
        if adm.in_flight(WorkClass.BULK_SCAN) == 0:
            break
        await asyncio.sleep(0.02)
    assert adm.in_flight(WorkClass.BULK_SCAN) == 0
    assert await adm.run(WorkClass.BULK_SCAN, lambda: 7, timeout=0.5) == 7


@pytest.mark.asyncio
async def test_permit_release_is_idempotent_and_failed_work_frees_the_slot():
    adm = Admission({WorkClass.EXPORT: 1})
    p = await adm.acquire(WorkClass.EXPORT)
    p.release(); p.release()
    assert adm.in_flight(WorkClass.EXPORT) == 0

    def boom():
        raise ValueError("x")

    with pytest.raises(ValueError):
        await adm.run(WorkClass.EXPORT, boom)
    await asyncio.sleep(0)
    assert adm.in_flight(WorkClass.EXPORT) == 0
