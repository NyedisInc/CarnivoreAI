
from __future__ import annotations

import asyncio
import codecs
from typing import Any, Callable, Optional, Protocol, TypeVar

import structlog

logger = structlog.get_logger()

DEFAULT_IDLE_FLUSH_SECONDS: float = 0.2


RELAY_TAIL_BYTES = 2048

RELAY_MAX_BUFFER = 65536


class RedactorUnavailableError(RuntimeError):
    pass


_MINT = object()


class Scrubbed(bytes):

    def __new__(cls, data: bytes = b"", mint: object = None) -> "Scrubbed":
        if mint is not _MINT:
            raise TypeError("Scrubbed is minted only by a SpectatorScrubber")
        return super().__new__(cls, data)


class Redactor(Protocol):

    def feed(self, chunk: str) -> str:
        ...

    def flush(self) -> str:
        ...

    @property
    def stats(self) -> Any:
        ...


RedactorFactory = Callable[[], Redactor]

_T = TypeVar("_T")


async def _off_loop(call: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    work = asyncio.ensure_future(asyncio.to_thread(call, *args, **kwargs))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        await asyncio.wait({work})
        if not work.cancelled() and work.exception() is not None:
            logger.warning("spectator_redaction_failed_during_cancel",
                           error=type(work.exception()).__name__)
        raise


def default_redactor_factory() -> Redactor:
    try:
        from src.core.stream_redactor import StreamRedactor
    except ImportError as exc:
        raise RedactorUnavailableError(
            f"src.core.stream_redactor is not importable: {exc}"
        ) from exc
    return StreamRedactor()


class SpectatorScrubber:

    def __init__(
        self,
        redactor: Redactor,
        *,
        label: str,
        idle_flush_seconds: float = DEFAULT_IDLE_FLUSH_SECONDS,
    ) -> None:
        self._redactor = redactor
        self._decoder = codecs.getincrementaldecoder("utf-8")("surrogateescape")
        self._label = label
        self._pending = False
        self._findings_logged = 0
        self.idle_flush_seconds = idle_flush_seconds

    @property
    def pending(self) -> bool:
        return self._pending

    def scrub(self, data: bytes) -> Scrubbed:
        released = self._redactor.feed(self._decoder.decode(data))
        self._pending = True
        self._note_findings()
        return _encode(released)

    def flush(self, *, final: bool = False) -> Scrubbed:
        text = self._decoder.decode(b"", final=True) if final else ""
        released = self._redactor.feed(text) if text else ""
        released += self._redactor.flush()
        self._pending = False
        self._note_findings()
        return _encode(released)

    async def scrub_off_loop(self, data: bytes) -> Scrubbed:
        return await _off_loop(self.scrub, data)

    async def flush_off_loop(self, *, final: bool = False) -> Scrubbed:
        return await _off_loop(self.flush, final=final)

    def summary(self) -> dict:
        stats = self._redactor.stats
        return {
            "chunks_in": int(stats.chunks_in),
            "findings": int(stats.findings),
            "detectors": list(stats.detectors),
        }

    def log_summary(self) -> None:
        logger.info("spectator_redaction_summary", label=self._label, **self.summary())

    def _note_findings(self) -> None:
        summary = self.summary()
        if summary["findings"] > self._findings_logged:
            self._findings_logged = summary["findings"]
            logger.info("spectator_redaction_applied", label=self._label, **summary)


def _encode(text: str) -> Scrubbed:
    return Scrubbed(text.encode("utf-8", "surrogateescape"), _MINT)


def relay_redactor_factory() -> Redactor:
    try:
        from src.core.stream_redactor import StreamRedactor
    except ImportError as exc:
        raise RedactorUnavailableError(
            f"src.core.stream_redactor is not importable: {exc}"
        ) from exc
    return StreamRedactor(tail_bytes=RELAY_TAIL_BYTES, max_buffer=RELAY_MAX_BUFFER)


def build_scrubber(
    *,
    label: str,
    factory: Optional[RedactorFactory] = None,
    idle_flush_seconds: float = DEFAULT_IDLE_FLUSH_SECONDS,
) -> SpectatorScrubber:
    build = factory or default_redactor_factory
    try:
        redactor = build()
    except RedactorUnavailableError:
        raise
    except (TypeError, ValueError, RuntimeError, ImportError) as exc:
        raise RedactorUnavailableError(
            f"redactor construction failed: {type(exc).__name__}"
        ) from exc
    return SpectatorScrubber(
        redactor, label=label, idle_flush_seconds=idle_flush_seconds
    )
