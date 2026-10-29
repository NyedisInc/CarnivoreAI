
from __future__ import annotations

from typing import Any, List, Mapping, Optional
from urllib.parse import quote

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_SPEAK, CAP_TRANSCRIBE, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_ELEVENLABS,
    Connection, ModelInfo, ProviderHTTPError, SpeechAudio, Target, TestResult, Transcript,
)
from src.core.byoai.media._common import audio_filename, multipart, speech_test, stream_audio

PROTOCOL = PROTO_ELEVENLABS
CAPABILITIES = frozenset({CAP_SPEAK, CAP_TRANSCRIBE})
EXTRAS = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST})

DEFAULT_SPEAK_MODEL = "eleven_flash_v2_5"
DEFAULT_TRANSCRIBE_MODEL = "scribe_v1"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"
FALLBACK_TTS_MODELS = ("eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_multilingual_v2")
DEFAULT_FORMAT = "mp3_44100_128"
SCRIBE_MODELS = ("scribe_v1", "scribe_v2")


def _mime_for(output_format: str) -> str:
    codec = output_format.split("_", 1)[0]
    return {"mp3": "audio/mpeg", "pcm": "audio/pcm", "ulaw": "audio/basic",
            "alaw": "audio/alaw", "opus": "audio/ogg"}.get(codec, "application/octet-stream")


async def speak(target: Target, key: Optional[str], text: str,
                options: Mapping[str, Any]) -> SpeechAudio:
    fmt = str(options.get("format") or DEFAULT_FORMAT)
    body: dict = {"text": text, "model_id": target.model or DEFAULT_SPEAK_MODEL}
    if options.get("voice_settings"):
        body["voice_settings"] = options["voice_settings"]
    body.update(options.get("extra") or {})
    path = f"/v1/text-to-speech/{quote(target.voice or DEFAULT_VOICE, safe='')}/stream"
    return await stream_audio(target.connection, key, "POST", path, _mime_for(fmt),
                              json=body, params={"output_format": fmt})


async def transcribe(target: Target, key: Optional[str], audio: bytes, mime: str,
                     options: Mapping[str, Any]) -> Transcript:
    fields = {"model_id": target.model or DEFAULT_TRANSCRIBE_MODEL}
    if options.get("language"):
        fields["language_code"] = str(options["language"])
    fields.update({k: str(v) for k, v in (options.get("extra") or {}).items()})
    content, headers = multipart(fields, "file", audio_filename(mime), audio, mime)
    body = (await transport.request_json(target.connection, key, "POST", "/v1/speech-to-text",
                                    content=content, headers=headers))
    words = [w for w in body.get("words") or [] if isinstance(w, dict) and isinstance(w.get("end"), (int, float))]
    return Transcript(text=str(body.get("text") or ""), language=body.get("language_code"),
                      duration_s=float(words[-1]["end"]) if words else None, raw=body)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    try:
        rows = (await transport.request_json(connection, key, "GET", "/v1/models", list_ok=True))
        tts = [(m["model_id"], str(m.get("name") or "")) for m in rows
               if isinstance(m, dict) and m.get("model_id") and m.get("can_do_text_to_speech")]
    except ProviderHTTPError as exc:
        if exc.status not in (401, 403):
            raise
        tts = [(m, m) for m in FALLBACK_TTS_MODELS]
    try:
        voices = (await transport.request_json(connection, key, "GET", "/v1/voices")).get("voices", [])
    except ProviderHTTPError as exc:
        if exc.status not in (401, 403):
            raise
        voices = []
    voice_meta = [{"id": v.get("voice_id"), "name": v.get("name"), "category": v.get("category")}
                  for v in voices if isinstance(v, dict) and v.get("voice_id")]
    out = [ModelInfo(id=mid, capabilities=(CAP_SPEAK,), label=label, meta={"voices": voice_meta})
           for mid, label in tts]
    out.extend(ModelInfo(id=s, capabilities=(CAP_TRANSCRIBE,), label=s) for s in SCRIBE_MODELS)
    return out


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    return await speech_test(speak, transcribe, target, key, capability)
