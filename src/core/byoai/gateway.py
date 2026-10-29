
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, List, Mapping, Optional, Sequence, Tuple, Union

import structlog

from src.config.byoai import ByoaiConfig, ConnectionConfig, TargetRef
from src.core.byoai import adapters, decide as decide_module, registry, transport
from src.core.byoai.calllog import CallLog, CallRecord
from src.core.byoai.contracts import (
    AUTH_CLI_ACCOUNT, AUTH_NONE, CAP_AGENT, CAP_AUDIO, CAP_CHAT, CAP_DECIDE, CAP_EMBED, CAP_IMAGE,
    CAP_SPEAK, CAP_TRANSCRIBE, CAP_VIDEO, AgentRequest, AgentResult, ByoaiError, ByoaiUnreachable, ChatDelta, ChatRequest,
    ChatResult, Connection, DecideRequest, DecideResult, EmbedResult, MediaResult, ModelInfo, NotConfigured, ProviderHTTPError, SpeechAudio, Target, TestResult, Transcript,
    Unsupported, Usage, to_connection,
)
from src.core.byoai.keys import KeyStore
from src.core.byoai.messages import as_messages, assistant as assistant, system_turn as system_turn, tool_result as tool_result, user as user  # noqa: F401
from src.core.byoai.model_catalog import discover, with_overrides
from src.core.byoai.presets import auth_style, enabled_capabilities, get_preset, protocol_for
from src.core.byoai.store import ByoaiStore

logger = structlog.get_logger()

Ref = Union[str, Target]

GENERATE_CAPABILITIES = (CAP_IMAGE, CAP_VIDEO, CAP_AUDIO)


def _usage_of(result: Any) -> Optional[Usage]:
    return result.usage if isinstance(result, (ChatResult, EmbedResult, DecideResult, AgentResult, MediaResult)) else None


@dataclass(frozen=True)
class Resolved:

    target: Target
    protocol: str
    feature: Optional[str] = None


class Gateway:

    def __init__(self, store: ByoaiStore, calllog: CallLog, keys: KeyStore, *,
                 features: Optional[registry.FeatureRegistry] = None) -> None:
        self.store = store
        self.calllog = calllog
        self.keys = keys
        self._features = features or registry.DEFAULT

    def connection(self, connection_id: str, block: Optional[ByoaiConfig] = None) -> Connection:
        for item in (block or self.store.read()).connections:
            if item.id == connection_id:
                return to_connection(item)
        raise NotConfigured(f"no connection {connection_id}")

    def _stored(self, target: Target) -> Target:
        return Target(self.connection(target.connection.id), target.model, target.voice)

    def target(self, connection_id: str, model: Optional[str] = None, voice: Optional[str] = None) -> Target:
        return Target(self.connection(connection_id), model, voice)

    def _from_ref(self, block: ByoaiConfig, ref: TargetRef) -> Target:
        connection = self.connection(ref.connection, block)
        model = ref.model or next(iter(get_preset(connection.preset).default_models), None)
        return Target(connection, model, ref.voice)

    def feature_target(self, feature_id: str) -> Optional[Target]:
        block = self.store.read()
        route = block.features.get(feature_id)
        return None if route is None else self._from_ref(block, route)

    def _serving(self, target: Target, capabilities: Tuple[str, ...], feature: Optional[str]) -> Resolved:
        connection = target.connection
        preset = get_preset(connection.preset)
        if not connection.enabled:
            raise NotConfigured(f"connection {connection.id} is switched off")
        if target.model and connection.models.get(target.model, {}).get("enabled") is False:
            raise NotConfigured(f"model {target.model} is switched off on {connection.id}")
        offered = enabled_capabilities(preset, connection.options)
        for capability in capabilities:
            if capability in offered:
                return Resolved(target, protocol_for(preset, connection.options, capability), feature)
        raise NotConfigured(f"{preset.id} does not offer {capabilities[0]}")

    def resolve(self, ref: Ref, capability: str, *, also: Tuple[str, ...] = (),
                feature: Optional[str] = None) -> Resolved:
        wanted = (capability,) + also
        if isinstance(ref, Target):
            return self._serving(self._stored(ref), wanted, feature)
        feature = self._features.get(ref)
        if feature and feature.capability != capability:
            raise ByoaiError(f"feature {ref} needs {feature.capability}, not {capability}")
        block = self.store.read()
        route = block.features.get(ref) or block.defaults.get(capability)
        if route is None:
            raise NotConfigured(f"{ref} has no connection chosen and there is no default for {capability}")
        return self._serving(self._from_ref(block, route), wanted, ref)

    async def _key(self, connection: Connection) -> Optional[str]:
        if auth_style(get_preset(connection.preset), connection.options) in (AUTH_NONE, AUTH_CLI_ACCOUNT):
            return None
        return await asyncio.to_thread(self.keys.get, connection.id)

    async def _log(self, capability: str, resolved: Resolved, started: float, *, ok: bool,
                   usage: Optional[Usage] = None, error: Optional[str] = None, key: Optional[str] = None) -> None:
        target = resolved.target
        text = transport.scrub(error, key) if error else None
        row = CallRecord(capability=capability, ok=ok, feature=resolved.feature, connection_id=target.connection.id,
                         preset=target.connection.preset, model=target.model,
                         latency_ms=int((time.monotonic() - started) * 1000),
                         input_tokens=usage.input_tokens if usage else None,
                         output_tokens=usage.output_tokens if usage else None,
                         cost_usd=usage.cost_usd if usage else None, error=text)
        try:
            await asyncio.to_thread(self.calllog.record, row)
        except (sqlite3.Error, RuntimeError, OSError) as exc:
            logger.warning("byoai_calllog_write_failed", error=type(exc).__name__)

    @staticmethod
    def _error_text(exc: ByoaiError) -> str:
        if isinstance(exc, ProviderHTTPError):
            return f"{exc.status}: {exc.body}"
        return f"unreachable: {exc}" if isinstance(exc, ByoaiUnreachable) else str(exc)

    async def _run(self, capability: str, resolved: Resolved,
                   call: Callable[[Optional[str]], Awaitable[Any]],
                   usage_of: Callable[[Any], Optional[Usage]] = lambda r: _usage_of(r),
                   ok_of: Callable[[Any], bool] = lambda r: True) -> Any:
        started = time.monotonic()
        key: Optional[str] = None
        try:
            key = await self._key(resolved.target.connection)
            result = await call(key)
        except ByoaiError as exc:
            await self._log(capability, resolved, started, ok=False, error=self._error_text(exc), key=key)
            raise
        ok = ok_of(result)
        await self._log(capability, resolved, started, ok=ok, usage=usage_of(result),
                        error=None if ok else "the call returned a result that is not ok")
        return result

    async def chat_request(self, ref: Ref, request: ChatRequest) -> ChatResult:
        r = self.resolve(ref, CAP_CHAT)
        return await self._run(CAP_CHAT, r, lambda key: adapters.chat(r.protocol, r.target, key, request))

    async def chat(self, ref: Ref, messages: Any, *, system: Optional[str] = None, tools: Sequence[Any] = (),
                   json_schema: Optional[Mapping[str, Any]] = None, max_tokens: Optional[int] = None,
                   temperature: Optional[float] = None, extra: Optional[Mapping[str, Any]] = None,
                   timeout_s: Optional[float] = None) -> ChatResult:
        return await self.chat_request(ref, ChatRequest(
            as_messages(messages), system, max_tokens, temperature, tuple(tools), json_schema, dict(extra or {}),
            timeout_s))

    async def chat_stream(self, ref: Ref, messages: Any, *, system: Optional[str] = None, tools: Sequence[Any] = (),
                          json_schema: Optional[Mapping[str, Any]] = None, max_tokens: Optional[int] = None,
                          temperature: Optional[float] = None,
                          extra: Optional[Mapping[str, Any]] = None,
                          timeout_s: Optional[float] = None) -> AsyncIterator[ChatDelta]:
        request = ChatRequest(as_messages(messages), system, max_tokens, temperature, tuple(tools),
                              json_schema, dict(extra or {}), timeout_s)
        r = self.resolve(ref, CAP_CHAT)
        started = time.monotonic()
        key: Optional[str] = None
        usage: Optional[Usage] = None
        try:
            key = await self._key(r.target.connection)
            async for delta in adapters.chat_stream(r.protocol, r.target, key, request):
                usage = delta.usage or usage
                yield delta
        except ByoaiError as exc:
            await self._log(CAP_CHAT, r, started, ok=False, error=self._error_text(exc), key=key)
            raise
        except GeneratorExit:
            await self._log(CAP_CHAT, r, started, ok=True, usage=usage)
            raise
        await self._log(CAP_CHAT, r, started, ok=True, usage=usage)

    async def embed(self, ref: Ref, inputs: Union[str, Sequence[str]]) -> EmbedResult:
        r = self.resolve(ref, CAP_EMBED)
        texts = [inputs] if isinstance(inputs, str) else list(inputs)
        return await self._run(CAP_EMBED, r, lambda key: adapters.embed(r.protocol, r.target, key, texts))

    async def decide(self, ref: Ref, *, state: Any, questions: Mapping[str, Mapping[str, Any]],
                     system: Optional[str] = None) -> DecideResult:
        r = self.resolve(ref, CAP_DECIDE, also=(CAP_CHAT,))
        request = DecideRequest(state, questions, system)
        if CAP_DECIDE in adapters.module_for(r.protocol).CAPABILITIES:
            return await self._run(CAP_DECIDE, r, lambda key: adapters.decide(r.protocol, r.target, key, request))
        chat_request = decide_module.chat_request(request)

        async def call(key: Optional[str]) -> DecideResult:
            reply = await adapters.chat(r.protocol, r.target, key, chat_request)
            return decide_module.parse(reply.text, questions, reply.usage, reply.raw)

        return await self._run(CAP_DECIDE, r, call)

    async def agent(self, ref: Ref, prompt: str, *, system: Optional[str] = None, allowed_tools: Sequence[str] = (),
                    permission_mode: Optional[str] = None, mcp: Optional[Mapping[str, Any]] = None,
                    cwd: Optional[str] = None, max_turns: Optional[int] = None,
                    timeout_s: Optional[float] = None, max_budget_usd: Optional[float] = None) -> AgentResult:
        r = self.resolve(ref, CAP_AGENT)
        request = AgentRequest(prompt, system, tuple(allowed_tools), permission_mode, mcp, cwd, max_turns, timeout_s,
                               max_budget_usd)
        return await self._run(CAP_AGENT, r, lambda key: adapters.run_agent(r.protocol, r.target, key, request))

    async def speak(self, ref: Ref, text: str, *, voice: Optional[str] = None, feature: Optional[str] = None,
                    **options: Any) -> SpeechAudio:
        r = self.resolve(ref, CAP_SPEAK, feature=feature)
        if voice:
            r = replace(r, target=replace(r.target, voice=voice))
        started = time.monotonic()
        key = await self._key(r.target.connection)
        try:
            audio = await adapters.speak(r.protocol, r.target, key, text, options)
        except ByoaiError as exc:
            await self._log(CAP_SPEAK, r, started, ok=False, error=self._error_text(exc), key=key)
            raise

        async def logged() -> AsyncIterator[bytes]:
            try:
                async for chunk in audio.chunks:
                    yield chunk
            except ByoaiError as exc:
                await self._log(CAP_SPEAK, r, started, ok=False, error=self._error_text(exc), key=key)
                raise
            await self._log(CAP_SPEAK, r, started, ok=True)

        return SpeechAudio(audio.mime, logged())

    async def transcribe(self, ref: Ref, audio: bytes, mime: str, *, feature: Optional[str] = None,
                         **options: Any) -> Transcript:
        r = self.resolve(ref, CAP_TRANSCRIBE, feature=feature)
        return await self._run(CAP_TRANSCRIBE, r, lambda key: adapters.transcribe(
            r.protocol, r.target, key, audio, mime, options))

    async def generate(self, ref: Ref, prompt: str, input: Optional[Mapping[str, Any]] = None, *,
                       capability: Optional[str] = None, feature: Optional[str] = None) -> MediaResult:
        registered = None if isinstance(ref, Target) else self._features.get(ref)
        capability = capability or (registered.capability if registered else None)
        if capability not in GENERATE_CAPABILITIES:
            raise ByoaiError("say which to generate: image, video or audio")
        r = self.resolve(ref, capability, feature=feature)
        return await self._run(capability, r, lambda key: adapters.generate(
            r.protocol, capability, r.target, key, prompt, dict(input or {})))

    def _raw_resolve(self, ref: Ref, capability: Optional[str]) -> Resolved:
        if isinstance(ref, Target):
            return Resolved(self._stored(ref), "", None)
        feature = self._features.get(ref)
        capability = capability or (feature.capability if feature else None)
        if not capability:
            raise NotConfigured(f"{ref} is not a registered feature; say which capability's default to use")
        block = self.store.read()
        route = block.features.get(ref) or block.defaults.get(capability)
        if route is None:
            raise NotConfigured(f"{ref} has no connection chosen and there is no default for {capability}")
        target = self._from_ref(block, route)
        if not target.connection.enabled:
            raise NotConfigured(f"connection {target.connection.id} is switched off")
        return Resolved(target, "", ref)

    async def raw(self, ref: Ref, method: str, path: str, *, capability: Optional[str] = None, **kwargs: Any) -> Any:
        r = self._raw_resolve(ref, capability)
        started = time.monotonic()
        key: Optional[str] = None
        try:
            key = await self._key(r.target.connection)
            response = await transport.raw(r.target.connection, key, method, path, **kwargs)
        except ByoaiError as exc:
            await self._log("raw", r, started, ok=False, error=self._error_text(exc), key=key)
            raise
        await self._log("raw", r, started, ok=response.status_code < 400,
                        error=None if response.status_code < 400 else f"{response.status_code}")
        return response

    @asynccontextmanager
    async def raw_ws(self, ref: Ref, path: str, *, capability: Optional[str] = None, **kwargs: Any) -> AsyncIterator[Any]:
        r = self._raw_resolve(ref, capability)
        started = time.monotonic()
        key: Optional[str] = None
        try:
            key = await self._key(r.target.connection)
            manager = transport.raw_ws(r.target.connection, key, path, **kwargs)
            ws = await manager.__aenter__()
        except ByoaiError as exc:
            await self._log("raw_ws", r, started, ok=False, error=self._error_text(exc), key=key)
            raise
        await self._log("raw_ws", r, started, ok=True)
        try:
            yield ws
        finally:
            await manager.__aexit__(None, None, None)

    async def test(self, connection_id: str, capability: str, model: Optional[str] = None) -> TestResult:
        started = time.monotonic()
        try:
            target = self.target(connection_id, model)
            if not target.model:
                target = replace(target, model=next(iter(get_preset(target.connection.preset).default_models), None))
            r = self._serving(target, (capability,), None)
            result = await self._run(capability, r, lambda key: adapters.test(r.protocol, r.target, key, capability),
                                    ok_of=lambda res: res.ok)
        except Unsupported as exc:
            return TestResult(False, capability, int((time.monotonic() - started) * 1000), model, str(exc))
        except ByoaiError as exc:
            return TestResult(False, capability, int((time.monotonic() - started) * 1000), model, str(exc)[:300])
        return result

    async def list_models(self, connection_id: str, *, refresh: bool = False,
                          cached_only: bool = False) -> Tuple[float, List[ModelInfo]]:
        connection = self.connection(connection_id)
        cached = None if refresh else await asyncio.to_thread(self.calllog.get_models, connection_id)
        if cached is None and cached_only:
            return 0.0, with_overrides(connection, [])
        if cached is None:
            if not connection.enabled:
                raise NotConfigured(f"connection {connection.id} is switched off")
            found = await discover(connection, lambda protocol, call: self._run(
                "models", Resolved(Target(connection), protocol), call))
            await asyncio.to_thread(self.calllog.put_models, connection_id, found)
            cached = (time.time(), found)
        return cached[0], with_overrides(connection, cached[1])


_DEFAULT: Optional[Gateway] = None


def build_default() -> Gateway:
    """The gateway over this install's config.json, state directory and Keychain."""
    from src.config import settings

    return Gateway(ByoaiStore(Path(settings.auth_config_file).expanduser()), CallLog(settings.get_state_dir()), KeyStore())


def get_gateway() -> Gateway:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = build_default()
    return _DEFAULT


def set_gateway(gateway: Optional[Gateway]) -> None:
    global _DEFAULT
    _DEFAULT = gateway


choice = decide_module.choice
score = decide_module.score
yes_no = decide_module.yes_no


async def chat(ref: Ref, messages: Any, **options: Any) -> ChatResult:
    return await get_gateway().chat(ref, messages, **options)


def chat_stream(ref: Ref, messages: Any, **options: Any) -> AsyncIterator[ChatDelta]:
    return get_gateway().chat_stream(ref, messages, **options)


async def embed(ref: Ref, inputs: Union[str, Sequence[str]]) -> EmbedResult:
    return await get_gateway().embed(ref, inputs)


async def decide(ref: Ref, *, state: Any, questions: Mapping[str, Mapping[str, Any]],
                 system: Optional[str] = None) -> DecideResult:
    return await get_gateway().decide(ref, state=state, questions=questions, system=system)


async def agent(ref: Ref, prompt: str, **options: Any) -> AgentResult:
    return await get_gateway().agent(ref, prompt, **options)


async def speak(ref: Ref, text: str, **options: Any) -> SpeechAudio:
    return await get_gateway().speak(ref, text, **options)


async def transcribe(ref: Ref, audio: bytes, mime: str, **options: Any) -> Transcript:
    return await get_gateway().transcribe(ref, audio, mime, **options)


async def generate(ref: Ref, prompt: str, input: Optional[Mapping[str, Any]] = None, *,
                   capability: Optional[str] = None, feature: Optional[str] = None) -> MediaResult:
    return await get_gateway().generate(ref, prompt, input, capability=capability, feature=feature)


async def raw(ref: Ref, method: str, path: str, **kwargs: Any) -> Any:
    return await get_gateway().raw(ref, method, path, **kwargs)


def raw_ws(ref: Ref, path: str, **kwargs: Any) -> Any:
    return get_gateway().raw_ws(ref, path, **kwargs)


async def test(connection_id: str, capability: str, model: Optional[str] = None) -> TestResult:
    return await get_gateway().test(connection_id, capability, model)


async def list_models(connection_id: str, *, refresh: bool = False,
                      cached_only: bool = False) -> Tuple[float, List[ModelInfo]]:
    return await get_gateway().list_models(connection_id, refresh=refresh, cached_only=cached_only)
