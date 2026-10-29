
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Mapping, Optional, Protocol, Tuple

REGION = re.compile(r"[a-z]{2}(-[a-z]+)+-[0-9]{1,2}")

if TYPE_CHECKING:
    from src.config.byoai import ConnectionConfig

CAP_CHAT = "chat"
CAP_EMBED = "embed"
CAP_DECIDE = "decide"
CAP_AGENT = "agent"
CAP_SPEAK = "speak"
CAP_TRANSCRIBE = "transcribe"
CAP_IMAGE = "image"
CAP_VIDEO = "video"
CAP_AUDIO = "audio"

CAPABILITIES: Tuple[str, ...] = (
    CAP_CHAT, CAP_EMBED, CAP_DECIDE, CAP_AGENT, CAP_SPEAK, CAP_TRANSCRIBE,
    CAP_IMAGE, CAP_VIDEO, CAP_AUDIO,
)

FLAG_TOOLS = "tools"
FLAG_JSON = "json"
FLAG_VISION = "vision"

AUTH_BEARER = "bearer"
AUTH_X_API_KEY = "x-api-key"
AUTH_XI_API_KEY = "xi-api-key"
AUTH_FAL_KEY = "fal-key"
AUTH_CUSTOM_HEADER = "custom-header"
AUTH_NONE = "none"
AUTH_CLI_ACCOUNT = "cli-account"

PROTO_OPENAI_CHAT = "openai_chat"
PROTO_OPENAI_RESPONSES = "openai_responses"
PROTO_ANTHROPIC_MESSAGES = "anthropic_messages"
PROTO_CLAUDE_CLI = "claude_cli"
PROTO_CODEX_CLI = "codex_cli"
PROTO_JEV = "jev"
PROTO_OPENAI_AUDIO = "openai_audio"
PROTO_ELEVENLABS = "elevenlabs"
PROTO_XAI_SPEECH = "xai_speech"
PROTO_NVIDIA_SPEECH = "nvidia_speech"
PROTO_FAL = "fal"
PROTO_OPENAI_IMAGES = "openai_images"

KIND_LOCAL = "local"
KIND_CLOUD = "cloud"
KIND_CLI = "cli"

EXTRA_LIST_MODELS = "list_models"
EXTRA_TEST = "test"
EXTRA_CHAT_STREAM = "chat_stream"


MAX_TIMEOUT_S = 600.0


class ByoaiError(Exception):
    pass


class NotConfigured(ByoaiError):
    pass


class MissingKey(ByoaiError):
    pass


class InvalidKey(ByoaiError):
    pass


class StaleRevision(ByoaiError):
    pass


class ProviderHTTPError(ByoaiError):

    def __init__(self, status: int, body: str = "") -> None:
        super().__init__(f"provider answered {status}")
        self.status = status
        self.body = body


class ProviderTimeout(ByoaiError):
    pass


class ByoaiUnreachable(ByoaiError):
    pass


class Unsupported(ByoaiError):
    pass


class LoginExpired(ByoaiError):
    pass


@dataclass(frozen=True)
class PresetField:

    name: str
    kind: str = "text"
    choices: Tuple[str, ...] = ()
    default: Any = None
    required: bool = False


@dataclass(frozen=True)
class Preset:

    id: str
    label: str
    kind: str
    capabilities: Mapping[str, Tuple[str, ...]]
    base_url: str = ""
    auth: str = AUTH_BEARER
    key_required: bool = False
    auth_choices: Tuple[str, ...] = ()
    fields: Tuple[PresetField, ...] = ()
    docs_url: str = ""
    default_models: Tuple[str, ...] = ()
    model_source: str = "discover"
    featured: Tuple[str, ...] = ()
    popular_sort: str = ""
    popular_url: str = ""
    custom: bool = False


@dataclass
class Connection:

    id: str
    preset: str
    label: str = ""
    base_url: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    key_host: Optional[str] = None
    key_hint: str = ""
    models: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


def to_connection(item: "ConnectionConfig") -> Connection:
    data = item.model_dump()
    return Connection(**{**data, "models": {m: dict(o) for m, o in data["models"].items()}})


@dataclass(frozen=True)
class ModelInfo:

    id: str
    capabilities: Tuple[str, ...] = ()
    flags: Tuple[str, ...] = ()
    label: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)
    context_length: Optional[int] = None
    price_in: Optional[float] = None
    price_out: Optional[float] = None
    inputs: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Target:

    connection: Connection
    model: Optional[str] = None
    voice: Optional[str] = None


@dataclass(frozen=True)
class Usage:

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None


@dataclass(frozen=True)
class ToolSpec:

    name: str
    description: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatMessage:

    role: str
    content: str = ""
    tool_calls: Tuple[ToolCall, ...] = ()
    tool_call_id: Optional[str] = None


@dataclass(frozen=True)
class ChatRequest:

    messages: Tuple[ChatMessage, ...]
    system: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    tools: Tuple[ToolSpec, ...] = ()
    json_schema: Optional[Mapping[str, Any]] = None
    extra: Mapping[str, Any] = field(default_factory=dict)
    timeout_s: Optional[float] = None


@dataclass(frozen=True)
class ChatResult:

    text: str = ""
    tool_calls: Tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    finish_reason: Optional[str] = None
    raw: Any = None


@dataclass(frozen=True)
class ChatDelta:

    text: str = ""
    tool_calls: Tuple[ToolCall, ...] = ()
    usage: Optional[Usage] = None
    done: bool = False


@dataclass(frozen=True)
class DecideRequest:

    state: Any
    questions: Mapping[str, Mapping[str, Any]]
    system: Optional[str] = None


@dataclass(frozen=True)
class DecideResult:

    answers: Mapping[str, Any]
    usage: Usage = field(default_factory=Usage)
    raw: Any = None


@dataclass(frozen=True)
class EmbedResult:

    vectors: Tuple[Tuple[float, ...], ...]
    usage: Usage = field(default_factory=Usage)
    raw: Any = None


@dataclass(frozen=True)
class Transcript:

    text: str
    language: Optional[str] = None
    duration_s: Optional[float] = None
    raw: Any = None


@dataclass(frozen=True)
class SpeechAudio:

    mime: str
    chunks: AsyncIterator[bytes]


@dataclass(frozen=True)
class MediaItem:

    url: str
    mime: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    duration_s: Optional[float] = None
    data: Optional[bytes] = None


@dataclass(frozen=True)
class MediaResult:

    items: Tuple[MediaItem, ...]
    raw: Any = None
    usage: Optional[Usage] = None


UNATTENDED_AGENT_MODES: Tuple[str, ...] = ("bypassPermissions", "dontAsk", "danger-full-access")


@dataclass(frozen=True)
class AgentRequest:

    prompt: str
    system: Optional[str] = None
    allowed_tools: Tuple[str, ...] = ()
    permission_mode: Optional[str] = None
    mcp_config: Optional[Mapping[str, Any]] = None
    cwd: Optional[str] = None
    max_turns: Optional[int] = None
    timeout_s: Optional[float] = None
    max_budget_usd: Optional[float] = None


@dataclass(frozen=True)
class AgentResult:

    text: str = ""
    usage: Usage = field(default_factory=Usage)
    raw: Any = None


@dataclass(frozen=True)
class TestResult:

    __test__ = False

    ok: bool
    capability: str = ""
    latency_ms: Optional[int] = None
    model: Optional[str] = None
    detail: str = ""
    audio: Optional[bytes] = None
    audio_mime: str = ""


class Adapter(Protocol):

    PROTOCOL: str
    CAPABILITIES: frozenset
    EXTRAS: frozenset

    async def list_models(self, connection: Connection, key: Optional[str]) -> List[ModelInfo]: ...

    async def test(self, target: Target, key: Optional[str], capability: str) -> TestResult: ...

    async def chat(self, target: Target, key: Optional[str], request: ChatRequest) -> ChatResult: ...

    def chat_stream(self, target: Target, key: Optional[str], request: ChatRequest) -> AsyncIterator[ChatDelta]: ...

    async def embed(self, target: Target, key: Optional[str], inputs: List[str]) -> EmbedResult: ...

    async def decide(self, target: Target, key: Optional[str], request: DecideRequest) -> DecideResult: ...

    async def speak(self, target: Target, key: Optional[str], text: str, options: Mapping[str, Any]) -> SpeechAudio: ...

    async def transcribe(self, target: Target, key: Optional[str], audio: bytes, mime: str, options: Mapping[str, Any]) -> Transcript: ...

    async def generate(self, target: Target, key: Optional[str], prompt: str, input: Mapping[str, Any]) -> MediaResult: ...

    async def run_agent(self, target: Target, key: Optional[str], request: AgentRequest) -> AgentResult: ...
