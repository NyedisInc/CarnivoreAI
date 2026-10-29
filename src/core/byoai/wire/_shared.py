
from __future__ import annotations

import json
import re
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import httpx

from src.core.byoai.contracts import (
    CAP_CHAT, CAP_EMBED, CAP_IMAGE, FLAG_JSON, FLAG_TOOLS, FLAG_VISION, ByoaiError, ChatMessage,
    ChatRequest, ChatResult, ModelInfo, NotConfigured, ProviderHTTPError, Target, TestResult,
)

_EMBED_ID = re.compile(r"embed|minilm|(^|[-/:])bge|(^|[-/:])e5-|(^|[-/:])gte-|nomic", re.I)

SMOKE_PROMPT = "Reply with the single word: ok"


def require_model(target: Target) -> str:
    if not target.model:
        raise NotConfigured(f"connection {target.connection.id} has no model chosen")
    return target.model


def parse_arguments(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {"_raw": str(raw)}
    return value if isinstance(value, dict) else {"_raw": str(raw)}


def dump_arguments(arguments: Mapping[str, Any]) -> str:
    return json.dumps(dict(arguments), separators=(",", ":"))


def system_text(request: ChatRequest) -> Optional[str]:
    parts = [request.system] if request.system else []
    parts += [m.content for m in request.messages if m.role == "system" and m.content]
    return "\n\n".join(parts) or None


def conversation(request: ChatRequest) -> List[ChatMessage]:
    return [m for m in request.messages if m.role != "system"]


def number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def whole(value: Any) -> Optional[int]:
    n = number(value)
    return None if n is None else int(n)


async def sse_events(response: httpx.Response) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
    event = ""
    async for line in response.aiter_lines():
        if not line:
            event = ""
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                payload = json.loads(data)
            except ValueError:
                raise ByoaiError("the stream sent a line that is not JSON") from None
            if isinstance(payload, dict):
                yield event, payload


def infer_model(model_id: str, entry: Mapping[str, Any]) -> ModelInfo:
    arch = entry.get("architecture") if isinstance(entry.get("architecture"), Mapping) else {}
    params = entry.get("supported_parameters") if isinstance(entry.get("supported_parameters"), list) else []
    outputs = arch.get("output_modalities") or []
    flags: List[str] = []
    if "tools" in params:
        flags.append(FLAG_TOOLS)
    if "response_format" in params or "structured_outputs" in params:
        flags.append(FLAG_JSON)
    if "image" in (arch.get("input_modalities") or []):
        flags.append(FLAG_VISION)
    if outputs and "text" not in outputs:
        caps: Tuple[str, ...] = (CAP_IMAGE,) if "image" in outputs else ()
    elif _EMBED_ID.search(model_id):
        caps = (CAP_EMBED,)
    else:
        caps = (CAP_CHAT, CAP_IMAGE) if "image" in outputs else (CAP_CHAT,)
    meta = {k: v for k, v in entry.items()
            if k in ("context_length", "pricing", "created", "owned_by", "display_name", "name")}
    label = str(entry.get("display_name") or entry.get("name") or "")
    pricing = entry.get("pricing") if isinstance(entry.get("pricing"), Mapping) else {}
    price_in, price_out = _per_million(pricing.get("prompt")), _per_million(pricing.get("completion"))
    context = whole(entry.get("context_length") or entry.get("context_window") or entry.get("max_model_len"))
    providers = [p for p in entry.get("providers") or [] if isinstance(p, Mapping)]
    if providers:
        if FLAG_TOOLS not in flags and any(p.get("supports_tools") for p in providers):
            flags.append(FLAG_TOOLS)
        prices = [p["pricing"] for p in providers if isinstance(p.get("pricing"), Mapping)]
        cheapest = min(prices, key=lambda x: number(x.get("input")) or 0.0) if prices else {}
        price_in = price_in if price_in is not None else number(cheapest.get("input"))
        price_out = price_out if price_out is not None else number(cheapest.get("output"))
        context = context or max((whole(p.get("context_length")) or 0 for p in providers), default=0) or None
    return ModelInfo(id=model_id, capabilities=caps, flags=tuple(flags), label=label, meta=meta,
                     context_length=context, price_in=price_in, price_out=price_out,
                     inputs=tuple(str(x) for x in arch.get("input_modalities") or ()),
                     outputs=tuple(str(x) for x in outputs))


def _per_million(per_token: Any) -> Optional[float]:
    try:
        value: Optional[float] = float(per_token) if isinstance(per_token, (str, int, float)) and not isinstance(per_token, bool) else None
    except ValueError:
        value = None
    return None if value is None or value < 0 else round(value * 1_000_000, 6)


async def smoke_test(target: Target, key: Optional[str], capability: str,
                     chat: Callable[[Target, Optional[str], ChatRequest], Awaitable[ChatResult]],
                     embed: Optional[Callable[[Target, Optional[str], List[str]], Awaitable[Any]]]) -> TestResult:
    if capability != CAP_CHAT and not (capability == CAP_EMBED and embed is not None):
        raise ByoaiError(f"no test for {capability}")
    started = time.monotonic()
    try:
        if capability == CAP_CHAT:
            result = await chat(target, key, ChatRequest(
                messages=(ChatMessage("user", SMOKE_PROMPT),), max_tokens=64))
            detail = (result.text.strip() or "(empty answer)")[:120]
        else:
            vectors = (await embed(target, key, ["ok"])).vectors
            detail = f"{len(vectors[0]) if vectors else 0} dimensions"
    except ByoaiError as exc:
        text = f"{exc}: {exc.body}" if isinstance(exc, ProviderHTTPError) and exc.body else str(exc)
        return TestResult(False, capability, int((time.monotonic() - started) * 1000), target.model, text[:300])
    return TestResult(True, capability, int((time.monotonic() - started) * 1000), target.model, detail)
