
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_SPEAK, CAP_TRANSCRIBE, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_XAI_SPEECH,
    ByoaiError, Connection, ModelInfo, SpeechAudio, Target, TestResult, Transcript,
)
from src.core.byoai.media._common import audio_filename, multipart, speech_test, stream_audio

PROTOCOL = PROTO_XAI_SPEECH
CAPABILITIES = frozenset({CAP_SPEAK, CAP_TRANSCRIBE})
EXTRAS = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST})

DEFAULT_VOICE = "eve"
DEFAULT_TRANSCRIBE_MODEL = "grok-voice-transcribe-2.0"
TRANSCRIBE_MODELS = ("grok-voice-transcribe-2.0", "grok-voice-transcribe-1.0")
TTS_MODEL = "grok-tts"
_MIMES = {"mp3": "audio/mpeg", "wav": "audio/wav", "pcm": "audio/pcm",
          "mulaw": "audio/basic", "alaw": "audio/alaw"}


async def speak(target: Target, key: Optional[str], text: str,
                options: Mapping[str, Any]) -> SpeechAudio:
    codec = str(options.get("format") or "mp3")
    out_format: dict = {"codec": codec}
    for src, dst in (("sample_rate", "sample_rate"), ("bit_rate", "bit_rate")):
        if options.get(src):
            out_format[dst] = options[src]
    body: dict = {"text": text, "voice_id": target.voice or DEFAULT_VOICE,
                  "language": str(options.get("language") or "en"), "output_format": out_format}
    body.update(options.get("extra") or {})
    return await stream_audio(target.connection, key, "POST", "/tts",
                              _MIMES.get(codec, "application/octet-stream"), json=body)


async def transcribe(target: Target, key: Optional[str], audio: bytes, mime: str,
                     options: Mapping[str, Any]) -> Transcript:
    fields = {"model": target.model or DEFAULT_TRANSCRIBE_MODEL}
    if options.get("language"):
        fields["language"] = str(options["language"])
    fields.update({k: str(v) for k, v in (options.get("extra") or {}).items()})
    content, headers = multipart(fields, "file", audio_filename(mime), audio, mime)
    body = (await transport.request_json(target.connection, key, "POST", "/stt",
                                    content=content, headers=headers))
    duration = body.get("duration")
    return Transcript(text=str(body.get("text") or ""), language=body.get("language"),
                      duration_s=float(duration) if isinstance(duration, (int, float)) else None,
                      raw=body)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    voices: list = []
    try:
        body = (await transport.request_json(connection, key, "GET", "/tts/voices", list_ok=True))
        rows = body.get("voices", body) if isinstance(body, dict) else body
        voices = [{"id": v.get("voice_id") or v.get("id"), "name": v.get("name")}
                  for v in rows if isinstance(v, dict)]
    except (ByoaiError, ValueError):
        voices = []
    return ([ModelInfo(id=TTS_MODEL, capabilities=(CAP_SPEAK,), meta={"voices": voices})]
            + [ModelInfo(id=m, capabilities=(CAP_TRANSCRIBE,)) for m in TRANSCRIBE_MODELS])


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    return await speech_test(speak, transcribe, target, key, capability)
