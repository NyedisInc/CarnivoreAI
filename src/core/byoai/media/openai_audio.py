
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_SPEAK, CAP_TRANSCRIBE, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_OPENAI_AUDIO,
    Connection, ModelInfo, SpeechAudio, Target, TestResult, Transcript,
)
from src.core.byoai.media._common import (
    audio_filename, guess_capabilities, multipart, speech_test, stream_audio,
)

PROTOCOL = PROTO_OPENAI_AUDIO
CAPABILITIES = frozenset({CAP_SPEAK, CAP_TRANSCRIBE})
EXTRAS = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST})

DEFAULT_SPEAK_MODEL = "gpt-4o-mini-tts"
DEFAULT_TRANSCRIBE_MODEL = "whisper-1"
DEFAULT_VOICE = "alloy"

_MIMES = {"mp3": "audio/mpeg", "wav": "audio/wav", "pcm": "audio/pcm", "opus": "audio/ogg",
          "flac": "audio/flac", "aac": "audio/aac"}


async def speak(target: Target, key: Optional[str], text: str,
                options: Mapping[str, Any]) -> SpeechAudio:
    fmt = str(options.get("format") or "mp3")
    body: dict = {"model": target.model or DEFAULT_SPEAK_MODEL, "input": text,
                  "voice": target.voice or DEFAULT_VOICE, "response_format": fmt}
    for name in ("speed", "instructions"):
        if options.get(name) is not None:
            body[name] = options[name]
    body.update(options.get("extra") or {})
    return await stream_audio(target.connection, key, "POST", "/audio/speech",
                              _MIMES.get(fmt, "application/octet-stream"), json=body)


async def transcribe(target: Target, key: Optional[str], audio: bytes, mime: str,
                     options: Mapping[str, Any]) -> Transcript:
    fields = {"model": target.model or DEFAULT_TRANSCRIBE_MODEL, "response_format": "json"}
    for name in ("language", "prompt"):
        if options.get(name):
            fields[name] = str(options[name])
    fields.update({k: str(v) for k, v in (options.get("extra") or {}).items()})
    content, headers = multipart(fields, "file", audio_filename(mime), audio, mime)
    body = (await transport.request_json(target.connection, key, "POST", "/audio/transcriptions",
                                    content=content, headers=headers))
    duration = body.get("duration")
    return Transcript(text=str(body.get("text") or ""), language=body.get("language"),
                      duration_s=float(duration) if isinstance(duration, (int, float)) else None,
                      raw=body)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    body = (await transport.request_json(connection, key, "GET", "/models"))
    return [ModelInfo(id=m["id"], capabilities=guess_capabilities(
                m["id"], ("tts", "kokoro", "speech", "voice"), ("whisper", "transcribe", "stt", "parakeet")))
            for m in body.get("data", []) if isinstance(m, dict) and m.get("id")]


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    return await speech_test(speak, transcribe, target, key, capability)
