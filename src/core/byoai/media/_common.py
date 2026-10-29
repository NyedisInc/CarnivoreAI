
from __future__ import annotations

import time
from contextlib import AsyncExitStack
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Sequence, Tuple

import httpx

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_SPEAK, CAP_TRANSCRIBE, Connection, SpeechAudio, Target, TestResult, Unsupported,
)
from src.core.byoai.media.test_clip import CLIP_TEXT, get_test_clip

TEST_PHRASE = "carnivore test"


def multipart(fields: Mapping[str, str], file_field: Optional[str] = None, filename: str = "",
              data: bytes = b"", mime: str = "") -> Tuple[bytes, Dict[str, str]]:
    parts: list = [(name, (None, value)) for name, value in fields.items()]
    if file_field:
        parts.append((file_field, (filename, data, mime)))
    request = httpx.Request("POST", "http://multipart.invalid/", files=parts)
    return request.read(), {"Content-Type": request.headers["content-type"]}


def audio_filename(mime: str) -> str:
    ext = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
           "audio/ogg": "ogg", "audio/flac": "flac", "audio/webm": "webm",
           "audio/mp4": "m4a", "audio/aac": "aac"}.get(mime.split(";")[0].strip().lower(), "wav")
    return f"audio.{ext}"


async def stream_audio(connection: Connection, key: Optional[str], method: str, path: str,
                       mime: str, **kwargs: Any) -> SpeechAudio:
    stack = AsyncExitStack()
    try:
        response = await stack.enter_async_context(
            transport.stream(connection, key, method, path, **kwargs))
    except BaseException:
        await stack.aclose()
        raise
    served = response.headers.get("content-type", "").split(";")[0].strip()
    actual = served if served.startswith("audio/") else mime

    async def chunks() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await stack.aclose()

    return SpeechAudio(mime=actual, chunks=chunks())


async def collect(audio: SpeechAudio) -> bytes:
    return b"".join([chunk async for chunk in audio.chunks])


def guess_capabilities(model_id: str, speak_words: Sequence[str],
                       transcribe_words: Sequence[str]) -> Tuple[str, ...]:
    lowered = model_id.lower()
    caps = []
    if any(w in lowered for w in speak_words):
        caps.append(CAP_SPEAK)
    if any(w in lowered for w in transcribe_words):
        caps.append(CAP_TRANSCRIBE)
    return tuple(caps)


async def speech_test(speak: Any, transcribe: Any, target: Target, key: Optional[str],
                      capability: str, clip_dir: Any = None) -> TestResult:
    started = time.monotonic()
    model = target.model
    if capability == CAP_SPEAK:
        audio = await speak(target, key, TEST_PHRASE, {})
        data = await collect(audio)
        ms = int((time.monotonic() - started) * 1000)
        return TestResult(ok=bool(data), capability=capability, latency_ms=ms, model=model,
                          detail=f"{len(data)} bytes of {audio.mime}" if data else "empty audio",
                          audio=data or None, audio_mime=audio.mime)
    if capability == CAP_TRANSCRIBE:
        clip = await get_test_clip(clip_dir)
        if clip is None:
            return TestResult(ok=False, capability=capability, model=model,
                              detail="could not test: no test clip on this computer")
        transcript = await transcribe(target, key, clip, "audio/wav", {})
        ms = int((time.monotonic() - started) * 1000)
        heard = transcript.text.strip()
        return TestResult(ok=bool(heard), capability=capability, latency_ms=ms, model=model,
                          detail=f"heard: {heard[:120]}" if heard else f"heard nothing (said: {CLIP_TEXT})")
    raise Unsupported(f"no test for {capability}")
