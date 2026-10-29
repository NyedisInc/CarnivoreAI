
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_SPEAK, CAP_TRANSCRIBE, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_NVIDIA_SPEECH,
    Connection, ModelInfo, SpeechAudio, Target, TestResult, Transcript,
)
from src.core.byoai.media._common import (
    audio_filename, guess_capabilities, multipart, speech_test, stream_audio,
)

PROTOCOL = PROTO_NVIDIA_SPEECH
CAPABILITIES = frozenset({CAP_SPEAK, CAP_TRANSCRIBE})
EXTRAS = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST})

DEFAULT_LANGUAGE = "en-US"
DEFAULT_SAMPLE_RATE = 22050


async def speak(target: Target, key: Optional[str], text: str,
                options: Mapping[str, Any]) -> SpeechAudio:
    fields = {"text": text, "language": str(options.get("language") or DEFAULT_LANGUAGE),
              "sample_rate_hz": str(options.get("sample_rate_hz") or DEFAULT_SAMPLE_RATE)}
    if target.voice:
        fields["voice"] = target.voice
    fields.update({k: str(v) for k, v in (options.get("extra") or {}).items()})
    content, headers = multipart(fields)
    return await stream_audio(target.connection, key, "POST", "/v1/audio/synthesize", "audio/wav",
                              content=content, headers=headers)


async def transcribe(target: Target, key: Optional[str], audio: bytes, mime: str,
                     options: Mapping[str, Any]) -> Transcript:
    fields = {"language": str(options.get("language") or DEFAULT_LANGUAGE), "response_format": "json"}
    fields.update({k: str(v) for k, v in (options.get("extra") or {}).items()})
    content, headers = multipart(fields, "file", audio_filename(mime), audio, mime)
    response = await transport.request(target.connection, key, "POST", "/v1/audio/transcriptions",
                                       content=content, headers=headers)
    try:
        body = response.json()
    except ValueError:
        body = {"text": response.text}
    return Transcript(text=str(body.get("text") or ""), language=body.get("language"), raw=body)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    body = (await transport.request(connection, key, "GET", "/v1/models")).json()
    return [ModelInfo(id=m["id"], capabilities=guess_capabilities(
                m["id"], ("magpie", "tts", "fastpitch"), ("parakeet", "asr", "canary", "whisper")))
            for m in body.get("data", []) if isinstance(m, dict) and m.get("id")]


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    return await speech_test(speak, transcribe, target, key, capability)
