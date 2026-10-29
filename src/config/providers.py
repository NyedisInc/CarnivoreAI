
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from src.models import MODEL_ID_PATTERN, is_valid_model_id


_DEFAULT_PROVIDER_MODELS: List[str] = [
    "qwen/qwen3.8-max",
    "moonshotai/kimi-k3",
    "openai/gpt-5.6-sol",
]


def _warn_bad_local_host(raw: str, why: str) -> None:
    import structlog

    structlog.get_logger().warning(
        "dropped_invalid_local_host", value=raw[:120], reason=why
    )


class ProvidersConfig(BaseModel):
    """OpenRouter model catalog for the provider-selector modal.

    ``models`` is the add/remove-able list shown alongside the implicit
    "Claude" option (never stored here, never removable - the client
    always prepends it). A missing/absent "providers" block in
    config.json deserializes to the curated default trio via
    ``_DEFAULT_PROVIDER_MODELS``.
    """
    models: List[str] = Field(default_factory=lambda: list(_DEFAULT_PROVIDER_MODELS))

    local_host: str = Field(
        default="",
        description="LM Studio server as host:port; empty means not configured",
    )

    @field_validator("local_host")
    @classmethod
    def _validate_local_host(cls, v: str) -> str:
        raw = (v or "").strip()
        if not raw:
            return ""
        if any(c in raw for c in "/\\?#@ \t'\"`$;|&<>()"):
            _warn_bad_local_host(raw, "must be host:port with no scheme or path")
            return ""
        host, sep, port = raw.rpartition(":")
        if not sep or not host:
            _warn_bad_local_host(raw, "missing :port")
            return ""
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            _warn_bad_local_host(raw, "port is not 1-65535")
            return ""
        if ":" in host and not (host.startswith("[") and host.endswith("]")):
            _warn_bad_local_host(raw, "bare IPv6 host must be bracketed")
            return ""
        return raw

    @field_validator("models")
    @classmethod
    def _drop_invalid_model_ids(cls, v: List[str]) -> List[str]:
        valid: List[str] = []
        dropped: List[str] = []
        for m in v:
            if isinstance(m, str) and is_valid_model_id(m):
                valid.append(m)
            else:
                dropped.append(m)
        if dropped:
            import structlog
            structlog.get_logger().warning(
                "dropped_invalid_provider_model_ids",
                dropped=dropped,
                pattern=MODEL_ID_PATTERN,
            )
        return valid
