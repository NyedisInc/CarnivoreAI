
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.api.error_response import api_error
from src.api.ai_common import api_errors
from src.api.auth import require_auth
from src.api.capped_reads import read_capped_body
from src.core.byoai import gateway as gateway_module
from src.core.byoai.contracts import UNATTENDED_AGENT_MODES, ByoaiError, ToolSpec
from src.core.byoai.gateway import Gateway, Ref
from src.core.byoai.serialize import jsonable
from src.models.automations import UNATTENDED_PHRASE

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(require_auth)])

MAX_AUDIO_BYTES = 25 * 1024 * 1024


class Dest(BaseModel):
    """Where a call goes: a registered ``feature``, or ``connection`` + ``model`` (+ ``voice``)."""

    model_config = ConfigDict(extra="forbid")

    feature: Optional[str] = None
    connection: Optional[str] = None
    model: Optional[str] = None
    voice: Optional[str] = None

    @model_validator(mode="after")
    def _one_way(self) -> "Dest":
        if bool(self.feature) == bool(self.connection):
            raise ValueError("give a feature, or a connection and model")
        return self

    def ref(self, gw: Gateway) -> Ref:
        if self.feature:
            return self.feature
        return gw.target(self.connection or "", self.model, self.voice)


class ToolBody(BaseModel):
    """A tool offered to the model."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ChatBody(Dest):

    prompt: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None
    system: Optional[str] = None
    tools: List[ToolBody] = Field(default_factory=list)
    json_schema: Optional[Dict[str, Any]] = None
    max_tokens: Optional[int] = Field(default=None, ge=1)
    temperature: Optional[float] = None
    extra: Dict[str, Any] = Field(default_factory=dict)
    stream: bool = False

    @model_validator(mode="after")
    def _has_input(self) -> "ChatBody":
        if self.prompt is None and not self.messages:
            raise ValueError("give a prompt or messages")
        return self

    def turns(self) -> Union[str, List[Dict[str, Any]]]:
        return self.messages if self.messages else (self.prompt or "")

    def options(self) -> Dict[str, Any]:
        return {"system": self.system, "tools": [ToolSpec(t.name, t.description, t.parameters) for t in self.tools],
                "json_schema": self.json_schema, "max_tokens": self.max_tokens,
                "temperature": self.temperature, "extra": self.extra}


class EmbedBody(Dest):

    input: Union[str, List[str]]


class DecideBody(Dest):

    state: Any = None
    questions: Dict[str, Dict[str, Any]]
    system: Optional[str] = None


class AgentBody(Dest):

    prompt: str
    system: Optional[str] = None
    allowed_tools: List[str] = Field(default_factory=list)
    permission_mode: Optional[str] = None
    mcp_config: Optional[Dict[str, Any]] = None
    cwd: Optional[str] = None
    max_turns: Optional[int] = Field(default=None, ge=1)
    timeout_s: Optional[float] = Field(default=None, gt=0)
    acknowledge_unattended: Optional[str] = None

    @model_validator(mode="after")
    def _unattended_needs_the_phrase(self) -> "AgentBody":
        if self.permission_mode in UNATTENDED_AGENT_MODES and self.acknowledge_unattended != UNATTENDED_PHRASE:
            raise ValueError(f'permission mode {self.permission_mode} runs with no prompts; set acknowledge_unattended to "{UNATTENDED_PHRASE}"')
        return self


class SpeakBody(Dest):

    text: str
    options: Dict[str, Any] = Field(default_factory=dict)


class GenerateBody(Dest):

    prompt: str
    capability: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)


def _sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


async def _stream_chat(first: Any, rest: AsyncIterator[Any]) -> AsyncIterator[bytes]:
    try:
        yield _sse("delta", jsonable(first))
        async for delta in rest:
            yield _sse("delta", jsonable(delta))
    except ByoaiError as exc:
        failure = api_error(502, "byoai_provider_error", exc)
        yield _sse("error", failure.detail)


@router.post("/chat")
async def chat(body: ChatBody) -> Any:
    """One chat call: JSON, or SSE with ``stream: true`` (a ``delta`` event each, the last has ``done``)."""
    gw = gateway_module.get_gateway()
    with api_errors(gw):
        ref = body.ref(gw)
        if not body.stream:
            return jsonable(await gw.chat(ref, body.turns(), **body.options()))
        deltas = gw.chat_stream(ref, body.turns(), **body.options())
        try:
            first = await deltas.__anext__()
        except StopAsyncIteration:
            raise ByoaiError("the provider sent nothing") from None
    return StreamingResponse(_stream_chat(first, deltas), media_type="text/event-stream")


@router.post("/embed")
async def embed(body: EmbedBody) -> Dict[str, Any]:
    """Embeddings, one vector per input."""
    gw = gateway_module.get_gateway()
    with api_errors(gw):
        return jsonable(await gw.embed(body.ref(gw), body.input))


@router.post("/decide")
async def decide(body: DecideBody) -> Dict[str, Any]:
    """A decision: native (Jev) or a chat model through a JSON schema."""
    gw = gateway_module.get_gateway()
    with api_errors(gw):
        return jsonable(await gw.decide(body.ref(gw), state=body.state, questions=body.questions, system=body.system))


@router.post("/agent")
async def agent(body: AgentBody) -> Dict[str, Any]:
    """An agent run (``claude -p``, ``codex exec``)."""
    gw = gateway_module.get_gateway()
    with api_errors(gw):
        return jsonable(await gw.agent(
            body.ref(gw), body.prompt, system=body.system, allowed_tools=body.allowed_tools,
            permission_mode=body.permission_mode, mcp=body.mcp_config, cwd=body.cwd,
            max_turns=body.max_turns, timeout_s=body.timeout_s))


@router.post("/speak")
async def speak(body: SpeakBody) -> StreamingResponse:
    """Text to audio: the response body is the audio stream and its content type the audio mime."""
    gw = gateway_module.get_gateway()
    with api_errors(gw):
        audio = await gw.speak(body.ref(gw), body.text, **body.options)
        chunks = audio.chunks.__aiter__()
        try:
            first = await chunks.__anext__()
        except StopAsyncIteration:
            first = b""

    async def body_stream() -> AsyncIterator[bytes]:
        yield first
        async for chunk in chunks:
            yield chunk

    return StreamingResponse(body_stream(), media_type=audio.mime or "application/octet-stream")


@router.post("/transcribe")
async def transcribe(request: Request, feature: Optional[str] = None, connection: Optional[str] = None,
                     model: Optional[str] = None) -> Dict[str, Any]:
    """Audio to text. The raw request body is the audio and its Content-Type the mime
    (no multipart: the dependency is not installed). Other query parameters pass to the adapter as options."""
    try:
        dest = Dest(feature=feature, connection=connection, model=model)
    except ValueError:
        raise HTTPException(400, {"error": "invalid", "detail": "give a feature, or a connection and model"}) from None
    audio = await read_capped_body(request, MAX_AUDIO_BYTES)
    if not audio:
        raise HTTPException(400, {"error": "audio", "detail": "send the audio as the request body"})
    options: Mapping[str, Any] = {k: v for k, v in request.query_params.items()
                                  if k not in ("feature", "connection", "model")}
    gw = gateway_module.get_gateway()
    with api_errors(gw):
        mime = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
        return jsonable(await gw.transcribe(dest.ref(gw), audio, mime, **options))


@router.post("/generate")
async def generate(body: GenerateBody) -> Dict[str, Any]:
    """Generate an image, video or audio clip; the answer lists media URLs and metadata."""
    gw = gateway_module.get_gateway()
    with api_errors(gw):
        return jsonable(await gw.generate(body.ref(gw), body.prompt, body.input, capability=body.capability))
