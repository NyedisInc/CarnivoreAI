
from __future__ import annotations

from types import ModuleType
from typing import Any, AsyncIterator, List, Mapping, Optional

from src.core.byoai.contracts import (
    CAP_AGENT, CAP_AUDIO, CAP_CHAT, CAP_EMBED, CAP_DECIDE, CAP_IMAGE, CAP_SPEAK,
    CAP_TRANSCRIBE, CAP_VIDEO, EXTRA_CHAT_STREAM, EXTRA_LIST_MODELS, EXTRA_TEST,
    AgentRequest, AgentResult, ChatDelta, ChatRequest, ChatResult, Connection,
    DecideRequest, DecideResult, EmbedResult, MediaResult, ModelInfo, SpeechAudio,
    Target, TestResult, Transcript, Unsupported,
)
from src.core.byoai.media import elevenlabs, fal, nvidia_speech, openai_audio, openai_images, xai_speech
from src.core.byoai.native import claude_cli, codex_cli, jev
from src.core.byoai.wire import anthropic_messages, openai_chat, openai_responses

ADAPTERS: Mapping[str, ModuleType] = {
    m.PROTOCOL: m for m in (
        openai_chat, openai_responses, anthropic_messages, claude_cli, codex_cli, jev,
        openai_audio, elevenlabs, xai_speech, nvidia_speech, fal, openai_images,
    )
}


def module_for(protocol: str) -> ModuleType:
    try:
        return ADAPTERS[protocol]
    except KeyError:
        raise Unsupported(f"unknown protocol: {protocol}") from None


def _need_capability(protocol: str, capability: str) -> ModuleType:
    module = module_for(protocol)
    if capability not in module.CAPABILITIES:
        raise Unsupported(f"{protocol} does not implement {capability}")
    return module


def _need_extra(protocol: str, extra: str) -> ModuleType:
    module = module_for(protocol)
    if extra not in module.EXTRAS:
        raise Unsupported(f"{protocol} does not implement {extra}")
    return module


async def list_models(protocol: str, connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    return await _need_extra(protocol, EXTRA_LIST_MODELS).list_models(connection, key)


async def test(protocol: str, target: Target, key: Optional[str], capability: str) -> TestResult:
    return await _need_extra(protocol, EXTRA_TEST).test(target, key, capability)


async def chat(protocol: str, target: Target, key: Optional[str], request: ChatRequest) -> ChatResult:
    return await _need_capability(protocol, CAP_CHAT).chat(target, key, request)


def chat_stream(protocol: str, target: Target, key: Optional[str],
                request: ChatRequest) -> AsyncIterator[ChatDelta]:
    _need_capability(protocol, CAP_CHAT)
    return _need_extra(protocol, EXTRA_CHAT_STREAM).chat_stream(target, key, request)


async def embed(protocol: str, target: Target, key: Optional[str], inputs: List[str]) -> EmbedResult:
    return await _need_capability(protocol, CAP_EMBED).embed(target, key, inputs)


async def decide(protocol: str, target: Target, key: Optional[str], request: DecideRequest) -> DecideResult:
    return await _need_capability(protocol, CAP_DECIDE).decide(target, key, request)


async def speak(protocol: str, target: Target, key: Optional[str], text: str,
                options: Mapping[str, Any]) -> SpeechAudio:
    return await _need_capability(protocol, CAP_SPEAK).speak(target, key, text, options)


async def transcribe(protocol: str, target: Target, key: Optional[str], audio: bytes, mime: str,
                     options: Mapping[str, Any]) -> Transcript:
    return await _need_capability(protocol, CAP_TRANSCRIBE).transcribe(target, key, audio, mime, options)


async def generate(protocol: str, capability: str, target: Target, key: Optional[str], prompt: str,
                   input: Mapping[str, Any]) -> MediaResult:
    if capability not in (CAP_IMAGE, CAP_VIDEO, CAP_AUDIO):
        raise Unsupported(f"{capability} is not a generate capability")
    return await _need_capability(protocol, capability).generate(target, key, prompt, input)


async def run_agent(protocol: str, target: Target, key: Optional[str], request: AgentRequest) -> AgentResult:
    return await _need_capability(protocol, CAP_AGENT).run_agent(target, key, request)
