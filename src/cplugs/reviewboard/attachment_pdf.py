
from __future__ import annotations

import asyncio
import atexit
import functools
import queue
import threading
import time
import weakref
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.cplugs.reviewboard import attachment_guard, attachment_types as types, office_text, pdf_scan
from src.cplugs.reviewboard.errors import ActiveContentFile, ScannerBusy, UnscannableFile
from src.cplugs.reviewboard.pdf_streams import PdfUnreadable
from src.cplugs.sdk.file_secrets import CpuDeadline, Deadline, ScanTimeout

logger = structlog.get_logger()


@dataclass
class _Job:

    fn: Callable[[], None]
    started: "Future[None]" = field(default_factory=Future)
    done: "Future[None]" = field(default_factory=Future)


class _ScanWorker:

    def __init__(self) -> None:
        self._jobs: "queue.SimpleQueue[_Job]" = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self.started: Optional[float] = None

    def submit(self, fn: Callable[[], None]) -> _Job:
        job = _Job(fn)
        self._jobs.put(job)
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="pdf-scan", daemon=True)
                self._thread.start()
        return job

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if not job.done.set_running_or_notify_cancel():
                continue
            self.started = time.monotonic()
            if job.started.set_running_or_notify_cancel():
                job.started.set_result(None)
            try:
                job.done.set_result(job.fn())
            except BaseException as exc:
                job.done.set_exception(exc)
            finally:
                self.started = None

    def cancel_pending(self) -> None:
        try:
            while True:
                self._jobs.get_nowait().done.cancel()
        except queue.Empty:
            return


_WORKER = _ScanWorker()
atexit.register(_WORKER.cancel_pending)
_SLOTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()
SCAN_WAIT_SECONDS = 30.0
SCAN_CPU_SECONDS = 20.0
SCAN_WALL_BACKSTOP_SECONDS = 120.0


def scan_deadline() -> Deadline:
    return CpuDeadline(SCAN_CPU_SECONDS, SCAN_WALL_BACKSTOP_SECONDS)


def _is_pdf(name: str, data: bytes) -> bool:
    return (types.CLASS_BY_EXTENSION.get(attachment_guard.extension_of(name)) == types.PDF
            or types.PDF_HEADER in data[:types.PDF_HEADER_WINDOW])


def _candidates(checked: Sequence[Tuple[str, bytes]]) -> List[Tuple[str, bytes]]:
    return [(name, data) for name, data in checked if _is_pdf(name, data)]


def _slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _SLOTS:
        _SLOTS[loop] = asyncio.Semaphore(1)
    return _SLOTS[loop]


async def refuse_active_content(checked: Sequence[Tuple[str, bytes]], *, slug: str) -> None:
    candidates = _candidates(checked)
    if not candidates:
        return
    _fail_fast_if_stuck(candidates, slug)
    slot = _slot()
    try:
        await asyncio.wait_for(slot.acquire(), SCAN_WAIT_SECONDS)
    except asyncio.TimeoutError as exc:
        logger.warning("reviewboard_attach_pdf_scanner_busy", slug=slug, files=[n[:80] for n, _ in candidates])
        raise ScannerBusy("the PDF scanner is busy with another attach, so nothing was attached; try again in a moment") from exc
    try:
        job = _WORKER.submit(functools.partial(_scan, candidates, slug=slug))
        try:
            await asyncio.wait_for(asyncio.wrap_future(job.started), SCAN_WAIT_SECONDS)
        except asyncio.TimeoutError as exc:
            logger.warning("reviewboard_attach_pdf_scanner_busy", slug=slug, files=[n[:80] for n, _ in candidates])
            raise ScannerBusy("the PDF scanner is busy with another attach, so nothing was attached; try again in a moment") from exc
        try:
            await asyncio.wait_for(asyncio.wrap_future(job.done), SCAN_WALL_BACKSTOP_SECONDS)
        except asyncio.TimeoutError as exc:
            logger.error("reviewboard_attach_pdf_scan_overran", slug=slug, files=[n[:80] for n, _ in candidates], limit=SCAN_WALL_BACKSTOP_SECONDS)
            raise UnscannableFile(f"{', '.join(n[:80] for n, _ in candidates)} took too long to check for active content, so nothing was attached; try a smaller file",
                                  files=[{"file": n[:80], "reason": office_text.REASON_TIMEOUT} for n, _ in candidates]) from exc
    finally:
        slot.release()


def _fail_fast_if_stuck(candidates: Sequence[Tuple[str, bytes]], slug: str) -> None:
    started = _WORKER.started
    if started is not None and time.monotonic() - started > SCAN_WALL_BACKSTOP_SECONDS:
        logger.warning("reviewboard_attach_pdf_scanner_stuck", slug=slug, files=[n[:80] for n, _ in candidates])
        raise ScannerBusy("the PDF scanner is stuck on an earlier file, so nothing was attached; try again in a moment")


def check_pdfs(checked: Sequence[Tuple[str, bytes]], *, slug: str) -> None:
    candidates = _candidates(checked)
    if candidates:
        _scan(candidates, slug=slug)


def _scan(candidates: Sequence[Tuple[str, bytes]], *, slug: str) -> None:
    deadline = scan_deadline()
    unreadable: List[Dict[str, str]] = []
    active: List[Dict[str, object]] = []
    for name, data in candidates:
        try:
            found = pdf_scan.features(data, deadline)
        except PdfUnreadable as exc:
            unreadable.append({"file": name[:80], "reason": exc.reason})
            continue
        except ScanTimeout:
            unreadable.append({"file": name[:80], "reason": office_text.REASON_TIMEOUT})
            continue
        if found:
            active.append({"file": name[:80], "features": sorted(found)})
    if unreadable:
        logger.warning("reviewboard_attach_pdf_unscannable_refused", slug=slug, files=[u["file"] for u in unreadable],
                       reasons=sorted({u["reason"] for u in unreadable}))
        raise UnscannableFile(f"{', '.join(u['file'] for u in unreadable)} could not be read for an active-content check, so nothing was attached; "
                              "save it again without a password and attach again", files=unreadable)
    if not active:
        return
    logger.warning("reviewboard_attach_pdf_active_content", slug=slug, files=[a["file"] for a in active])
    raise ActiveContentFile(f"{', '.join(str(a['file']) for a in active)} carries active content, so nothing was attached; "
                            "save a copy without scripts, launch actions or embedded files and attach that", files=active)
