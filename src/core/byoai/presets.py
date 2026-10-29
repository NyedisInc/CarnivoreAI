
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from src.core.byoai.contracts import (
    REGION,
    AUTH_BEARER, AUTH_CLI_ACCOUNT, AUTH_CUSTOM_HEADER, AUTH_FAL_KEY, AUTH_NONE,
    AUTH_X_API_KEY, AUTH_XI_API_KEY, CAP_AGENT, CAP_AUDIO, CAP_CHAT, CAP_DECIDE,
    CAP_EMBED, CAP_IMAGE, CAP_SPEAK, CAP_TRANSCRIBE, CAP_VIDEO, KIND_CLI,
    KIND_CLOUD, KIND_LOCAL, PROTO_ANTHROPIC_MESSAGES, PROTO_CLAUDE_CLI,
    PROTO_CODEX_CLI, PROTO_ELEVENLABS, PROTO_FAL, PROTO_JEV, PROTO_NVIDIA_SPEECH,
    PROTO_OPENAI_AUDIO, PROTO_OPENAI_CHAT, PROTO_OPENAI_IMAGES,
    PROTO_OPENAI_RESPONSES, PROTO_XAI_SPEECH, ByoaiError, NotConfigured, Preset, PresetField,
)

_CHAT = PROTO_OPENAI_CHAT
_RESP = PROTO_OPENAI_RESPONSES
_ANTH = PROTO_ANTHROPIC_MESSAGES

JEV_MODEL = "jev-1.13.0"

CLAUDE_ALIASES = ("haiku", "sonnet", "opus")

_REGION = PresetField("region", "text", default="us-east-1", required=True)


def _vendor(pid: str, label: str, base: str, docs: str, *, embed: bool = False,
            extra: Tuple[str, ...] = (), featured: Tuple[str, ...] = ()) -> Preset:
    caps: Dict[str, Tuple[str, ...]] = {CAP_CHAT: (_CHAT,) + extra}
    if embed:
        caps[CAP_EMBED] = (_CHAT,)
    return Preset(pid, label, KIND_CLOUD, caps, base_url=base, key_required=True, docs_url=docs,
                  featured=featured)


_ALL: Tuple[Preset, ...] = (
    Preset("ollama", "ollama", KIND_LOCAL,
           {CAP_CHAT: (_CHAT, _ANTH), CAP_EMBED: (_CHAT,)},
           base_url="http://127.0.0.1:11434/v1", auth=AUTH_NONE,
           docs_url="https://github.com/ollama/ollama/blob/main/docs/openai.md"),
    Preset("lmstudio", "lm studio", KIND_LOCAL,
           {CAP_CHAT: (_CHAT, _RESP, _ANTH), CAP_EMBED: (_CHAT,)},
           base_url="http://127.0.0.1:1234/v1", auth=AUTH_BEARER,
           docs_url="https://lmstudio.ai/docs/developer"),
    Preset("anthropic", "anthropic", KIND_CLOUD, {CAP_CHAT: (_ANTH,)},
           base_url="https://api.anthropic.com", auth=AUTH_X_API_KEY, key_required=True,
           docs_url="https://docs.anthropic.com/en/api",
           featured=("claude-opus", "claude-sonnet", "claude-haiku")),
    Preset("claude_cli", "claude code cli", KIND_CLI,
           {CAP_CHAT: (PROTO_CLAUDE_CLI,), CAP_AGENT: (PROTO_CLAUDE_CLI,)},
           auth=AUTH_CLI_ACCOUNT,
           fields=(PresetField("account", "text"), PresetField("load_user_config", "bool", default=False)),
           docs_url="https://docs.anthropic.com/en/docs/claude-code",
           default_models=CLAUDE_ALIASES, model_source="fixed"),
    Preset("codex_cli", "codex cli", KIND_CLI,
           {CAP_CHAT: (PROTO_CODEX_CLI,), CAP_AGENT: (PROTO_CODEX_CLI,)},
           auth=AUTH_CLI_ACCOUNT,
           fields=(PresetField("account", "text"), PresetField("load_user_config", "bool", default=False)),
           docs_url="https://github.com/openai/codex", model_source="manual"),
    Preset("openrouter", "openrouter", KIND_CLOUD,
           {CAP_CHAT: (_CHAT, _RESP, _ANTH), CAP_EMBED: (_CHAT,),
            CAP_IMAGE: (PROTO_OPENAI_IMAGES,)},
           base_url="https://openrouter.ai/api/v1", key_required=True,
           docs_url="https://openrouter.ai/docs", popular_sort="top-weekly"),
    Preset("openai", "openai", KIND_CLOUD,
           {CAP_CHAT: (_RESP, _CHAT), CAP_EMBED: (_CHAT,),
            CAP_SPEAK: (PROTO_OPENAI_AUDIO,), CAP_TRANSCRIBE: (PROTO_OPENAI_AUDIO,),
            CAP_IMAGE: (PROTO_OPENAI_IMAGES,)},
           base_url="https://api.openai.com/v1", key_required=True,
           docs_url="https://platform.openai.com/docs/api-reference",
           featured=("gpt-5", "gpt-4.1", "gpt-4o", "o3", "o4-mini", "text-embedding-3")),
    Preset("xai", "xai (grok)", KIND_CLOUD,
           {CAP_CHAT: (_RESP, _CHAT, _ANTH), CAP_SPEAK: (PROTO_XAI_SPEECH,),
            CAP_TRANSCRIBE: (PROTO_XAI_SPEECH,), CAP_IMAGE: (PROTO_OPENAI_IMAGES,)},
           base_url="https://api.x.ai/v1", key_required=True, docs_url="https://docs.x.ai",
           featured=("grok-4", "grok-3", "grok-code")),
    Preset("nvidia", "nvidia", KIND_CLOUD,
           {CAP_CHAT: (_CHAT,), CAP_EMBED: (_CHAT,)},
           base_url="https://integrate.api.nvidia.com/v1", key_required=True,
           docs_url="https://docs.api.nvidia.com",
           featured=("nvidia/llama-3.3-nemotron", "meta/llama-3.3-70b", "deepseek-ai/deepseek", "qwen/qwen3")),
    Preset("nvidia_speech", "nvidia speech nim", KIND_LOCAL,
           {CAP_SPEAK: (PROTO_NVIDIA_SPEECH,), CAP_TRANSCRIBE: (PROTO_NVIDIA_SPEECH,)},
           auth=AUTH_BEARER, docs_url="https://docs.nvidia.com/nim/speech/latest/"),
    Preset("bedrock", "bedrock", KIND_CLOUD,
           {CAP_CHAT: (_CHAT,)},
           base_url="https://bedrock-runtime.{region}.amazonaws.com/openai/v1",
           key_required=True, fields=(_REGION,), model_source="manual",
           docs_url="https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html"),
    Preset("bedrock_anthropic", "bedrock claude", KIND_CLOUD,
           {CAP_CHAT: (_ANTH,)},
           base_url="https://bedrock-mantle.{region}.api.aws/anthropic",
           key_required=True, fields=(_REGION,), model_source="manual",
           docs_url="https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html"),
    Preset("jev", "jev (typesafe)", KIND_CLOUD, {CAP_DECIDE: (PROTO_JEV,)},
           base_url="https://api.typesafe.ai", key_required=True,
           docs_url="https://typesafe.ai", default_models=(JEV_MODEL,), model_source="fixed"),
    Preset("elevenlabs", "elevenlabs", KIND_CLOUD,
           {CAP_SPEAK: (PROTO_ELEVENLABS,), CAP_TRANSCRIBE: (PROTO_ELEVENLABS,)},
           base_url="https://api.elevenlabs.io", auth=AUTH_XI_API_KEY, key_required=True,
           docs_url="https://elevenlabs.io/docs/api-reference"),
    Preset("fal", "fal.ai", KIND_CLOUD,
           {CAP_IMAGE: (PROTO_FAL,), CAP_VIDEO: (PROTO_FAL,), CAP_AUDIO: (PROTO_FAL,)},
           base_url="https://queue.fal.run", auth=AUTH_FAL_KEY, key_required=True,
           docs_url="https://fal.ai/docs"),
    Preset("local_audio", "local audio server", KIND_LOCAL,
           {CAP_SPEAK: (PROTO_OPENAI_AUDIO,), CAP_TRANSCRIBE: (PROTO_OPENAI_AUDIO,)},
           auth=AUTH_BEARER),
    _vendor("gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://ai.google.dev/gemini-api/docs/openai", embed=True,
            featured=("gemini-3", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash")),
    _vendor("groq", "groq", "https://api.groq.com/openai/v1", "https://console.groq.com/docs",
            featured=("openai/gpt-oss-120b", "llama-3.3-70b", "llama-3.1-8b", "qwen")),
    _vendor("mistral", "mistral", "https://api.mistral.ai/v1", "https://docs.mistral.ai", embed=True,
            featured=("mistral-large", "mistral-medium", "mistral-small", "codestral")),
    _vendor("deepseek", "deepseek", "https://api.deepseek.com", "https://api-docs.deepseek.com",
            extra=(_ANTH,), featured=("deepseek-chat", "deepseek-reasoner")),
    _vendor("cerebras", "cerebras", "https://api.cerebras.ai/v1", "https://inference-docs.cerebras.ai",
            featured=("gpt-oss-120b", "llama-3.3-70b", "qwen-3")),
    Preset("huggingface", "hugging face", KIND_CLOUD, {CAP_CHAT: (_CHAT,)},
           base_url="https://router.huggingface.co/v1", key_required=True,
           docs_url="https://huggingface.co/docs/inference-providers",
           popular_url="https://huggingface.co/api/models?sort=trendingScore&limit=100&inference_provider=all",
           featured=("openai/gpt-oss-120b", "meta-llama/Llama-3.3-70B", "Qwen/Qwen3", "deepseek-ai/DeepSeek")),
    Preset("custom", "custom", KIND_CLOUD,
           {CAP_CHAT: (_CHAT, _RESP, _ANTH), CAP_EMBED: (_CHAT,)},
           auth=AUTH_BEARER, auth_choices=(AUTH_BEARER, AUTH_X_API_KEY, AUTH_CUSTOM_HEADER, AUTH_NONE),
           fields=(PresetField("auth", "choice", choices=(AUTH_BEARER, AUTH_X_API_KEY, AUTH_CUSTOM_HEADER, AUTH_NONE),
                               default=AUTH_BEARER),
                   PresetField("auth_header", "text"),
                   PresetField("protocol", "choice", choices=(_CHAT, _RESP, _ANTH)),
                   PresetField("capabilities", "text")),
           custom=True),
)

PRESETS: Mapping[str, Preset] = {p.id: p for p in _ALL}


def get_preset(preset_id: str) -> Preset:
    try:
        return PRESETS[preset_id]
    except KeyError:
        raise NotConfigured(f"unknown preset: {preset_id}") from None


def list_presets() -> Tuple[Preset, ...]:
    return _ALL


def default_base_url(preset: Preset, options: Optional[Mapping[str, Any]] = None) -> str:
    if "{region}" not in preset.base_url:
        return preset.base_url
    region = str((options or {}).get("region") or "us-east-1")
    if not REGION.fullmatch(region):
        raise ByoaiError("region must look like us-east-1")
    return preset.base_url.replace("{region}", region)


def auth_style(preset: Preset, options: Mapping[str, Any]) -> str:
    picked = options.get("auth")
    if preset.auth_choices and picked in preset.auth_choices:
        return str(picked)
    return preset.auth


def protocol_for(preset: Preset, options: Mapping[str, Any], capability: str) -> str:
    allowed = preset.capabilities.get(capability, ())
    if not allowed or capability not in enabled_capabilities(preset, options):
        raise NotConfigured(f"{preset.id} does not offer {capability}")
    picked = options.get("protocol")
    return picked if picked in allowed else allowed[0]


def enabled_capabilities(preset: Preset, options: Mapping[str, Any]) -> Tuple[str, ...]:
    offered = tuple(preset.capabilities)
    if not preset.custom:
        return offered
    ticked = options.get("capabilities") or []
    return tuple(c for c in offered if c in ticked)
