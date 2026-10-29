
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog

from src.cplugs.host.ai_budget import AiBudget
from src.cplugs.sdk.ai_features import AI_CAPABILITIES, AiFeature, feature_id

logger = structlog.get_logger()

ALLOWED_INPUT = {"chat": frozenset({"prompt", "max_tokens"}), "embed": frozenset({"inputs"})}
NO_TOOL_PROTOCOLS = frozenset({"openai_chat", "openai_responses", "anthropic_messages", "claude_cli"})
MAX_PROMPT_CHARS = 16_000
MAX_EMBED_INPUTS = 32
DEFAULT_MAX_TOKENS = 1024
MAX_OUTPUT_TOKENS = 2048
MAX_OUTPUT_CHARS = MAX_OUTPUT_TOKENS * 4
MAX_REFUSAL_ROWS = 50


class AiRefused(Exception):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def mask_secrets(text: str) -> str:
    from src.core.message_model_secrets import scan_text  # noqa: PLC0415

    for finding in sorted(scan_text(text, trust_vendor_marker=True), key=lambda f: f.offset, reverse=True):
        text = text[:finding.offset] + f"[secret:{finding.detector}:{finding.value_sha256[:8]}]" + text[finding.offset + finding.length:]
    return text


def estimate_tokens(texts: List[str], extra: int = 0) -> int:
    return sum(len(t) for t in texts) // 4 + extra


class PluginAi:

    def __init__(self, cplug_id: str, features: Mapping[str, AiFeature], budget: AiBudget,
                 gateway: Optional[Callable[[], Any]] = None) -> None:
        self._id = cplug_id
        self._features = dict(features)
        self._budget = budget
        self._gateway = gateway

    def _gw(self) -> Any:
        if self._gateway is not None:
            return self._gateway()
        from src.core.byoai import gateway  # noqa: PLC0415

        return gateway.get_gateway()

    async def _refuse(self, feature: str, capability: str, code: str, detail: str = "") -> AiRefused:
        if feature not in self._features:
            feature = f"cplug.{self._id}"
        logger.warning("cplug_ai_refused", cplug=self._id, feature=feature, capability=capability, code=code, detail=detail)
        try:
            if not await asyncio.to_thread(self._budget.note_refusal, self._id, MAX_REFUSAL_ROWS):
                logger.warning("cplug_ai_refusals_suppressed", cplug=self._id)
                return AiRefused(code, detail)
            from src.core.byoai.calllog import CallRecord  # noqa: PLC0415

            row = CallRecord(capability=capability if capability in AI_CAPABILITIES else "chat", ok=False,
                             feature=feature, error=f"cplug {self._id} refused: {code} {detail}"[:200])
            await asyncio.to_thread(self._gw().calllog.record, row)
        except (sqlite3.Error, RuntimeError, OSError) as exc:
            logger.warning("cplug_ai_refusal_unlogged", cplug=self._id, error_type=type(exc).__name__)
        return AiRefused(code, detail)

    def _checked_input(self, capability: str, data: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, Mapping):
            raise AiRefused("bad_input", "input must be an object")
        extra = sorted(str(k) for k in data if k not in ALLOWED_INPUT[capability])
        if extra:
            raise AiRefused("option_not_allowed", ", ".join(extra))
        if capability == "chat":
            prompt, size = data.get("prompt"), data.get("max_tokens", DEFAULT_MAX_TOKENS)
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
                raise AiRefused("bad_input", f"prompt must be text of 1 to {MAX_PROMPT_CHARS} characters")
            if prompt.lstrip().startswith("/"):
                raise AiRefused("bad_input", "prompt must not start with a slash")
            if not isinstance(size, int) or isinstance(size, bool) or size < 1:
                raise AiRefused("bad_input", "max_tokens must be a positive integer")
            return {"prompt": mask_secrets(prompt), "max_tokens": min(size, MAX_OUTPUT_TOKENS)}
        texts = data.get("inputs")
        if (not isinstance(texts, list) or not 1 <= len(texts) <= MAX_EMBED_INPUTS
                or not all(isinstance(t, str) and t.strip() and len(t) <= MAX_PROMPT_CHARS for t in texts)):
            raise AiRefused("bad_input", f"inputs must be 1 to {MAX_EMBED_INPUTS} texts of up to {MAX_PROMPT_CHARS} characters")
        return {"inputs": [mask_secrets(t) for t in texts]}

    def _check_route(self, feature: str, capability: str) -> None:
        gateway = self._gw()
        if gateway.store.read().features.get(feature) is None:
            raise AiRefused("not_routed", "the owner has not routed this feature in settings")
        from src.core.byoai.contracts import ByoaiError  # noqa: PLC0415

        try:
            resolved = gateway.resolve(feature, capability)
        except ByoaiError as exc:
            raise AiRefused("not_configured", str(exc)[:120]) from exc
        protocol = resolved.protocol
        if protocol == "claude_cli":
            from src.core.byoai.native import cli_run  # noqa: PLC0415

            if not cli_run.isolated(resolved.target.connection):
                raise AiRefused("provider_not_allowed", "claude_cli loads the owner's user config on this connection")
        if protocol not in NO_TOOL_PROTOCOLS:
            raise AiRefused("provider_not_allowed", f"{protocol} cannot run without tools")

    async def call(self, feature: str, capability: str, input: Mapping[str, Any]) -> Dict[str, Any]:
        declared = self._features.get(feature) if isinstance(feature, str) else None
        if declared is None:
            raise await self._refuse(str(feature), str(capability), "not_granted", "no such granted feature")
        if capability != declared.capability:
            code = "capability_not_allowed" if capability not in AI_CAPABILITIES else "bad_input"
            raise await self._refuse(feature, str(capability), code, f"this feature is {declared.capability}")
        try:
            clean = self._checked_input(capability, input)
            await asyncio.to_thread(self._check_route, feature, capability)
        except AiRefused as exc:
            raise await self._refuse(feature, capability, exc.code, str(exc)[len(exc.code) + 2:]) from exc
        try:
            spent = await asyncio.to_thread(self._budget.reserve, self._id, feature, declared.calls_per_day, declared.tokens_per_day)
        except (sqlite3.Error, OSError) as exc:
            raise await self._refuse(feature, capability, "budget_unavailable", type(exc).__name__) from exc
        if spent is not None:
            raise await self._refuse(feature, capability, "budget_exceeded", spent)
        gateway = self._gw()
        if capability == "chat":
            result = await gateway.chat(feature, clean["prompt"], max_tokens=clean["max_tokens"])
            output: Any = (result.text or "")[:MAX_OUTPUT_CHARS]
            used = (result.usage.input_tokens or 0) + (result.usage.output_tokens or 0) if result.usage else 0
            used = used or estimate_tokens([clean["prompt"], output])
        else:
            result = await gateway.embed(feature, clean["inputs"])
            output = [list(v) for v in result.vectors]
            used = (result.usage.input_tokens or 0) if result.usage else 0
            used = used or estimate_tokens(clean["inputs"])
        try:
            await asyncio.to_thread(self._budget.add_tokens, self._id, feature, used)
        except (sqlite3.Error, OSError) as exc:
            logger.error("cplug_ai_tokens_unrecorded", cplug=self._id, feature=feature, error_type=type(exc).__name__)
        return {"output": output}


def register_features(definitions: Any) -> None:
    from src.core.byoai import registry  # noqa: PLC0415

    for d in definitions:
        owner = registry.FeatureOwner(f"cplug.{d.id}", d.manifest.name_key, "plugins", page=f"#plugins/{d.id}/settings")
        for name, f in d.manifest.ai_features.items():
            fid = feature_id(d.id, name)
            if registry.get_feature(fid) is None:
                registry.register_feature(fid, f.capability, f"cplug.{d.id}.ai.{name}", group="cplugs", owner=owner)
