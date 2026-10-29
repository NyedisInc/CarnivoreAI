
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from src.core.session_token_usage.reader import SessionSubject, read_session_token_usage

_FAMILIES_WITH_READER = ("claude", "codex")


@dataclass(frozen=True)
class ModelListingFacts:

    model: Optional[str] = None
    model_effort: Optional[str] = None
    model_tier: Optional[int] = None
    family: Optional[str] = None
    context_used_pct: Optional[float] = None


_UNKNOWN = ModelListingFacts()


MAX_COLD_TRANSCRIPT_BYTES = 64 * 1024 * 1024


def _resolved_family_from_agent_type(agent_type: Optional[str]) -> Optional[str]:
    if not agent_type:
        return None
    from src.config import settings
    from src.core.agent_family_display import resolve_family_for_display

    try:
        wrappers = settings.load_auth_config().agents.wrappers or []
    except Exception:  # noqa: BLE001
        wrappers = []
    family, _source = resolve_family_for_display(str(agent_type), wrappers)
    return family.name if family else None


def _stored_agent_family(
    name: str, *, prefetch: Optional[Any]
) -> Optional[str]:
    if prefetch is None or not prefetch.has(name):
        return None
    identity = prefetch.identity_for(name) or {}
    family = identity.get("agent_family")
    if not family:
        family = _resolved_family_from_agent_type(identity.get("agent_type"))
    if not family:
        return None
    return str(family).strip().lower() or None


def _epoch_for_name(name: str, *, status_map: Optional[Any]) -> Optional[int]:
    if status_map is None:
        return None
    try:
        row = status_map.get(name)
    except AttributeError:
        return None
    if not row:
        return None
    epoch = row.get("created_at_epoch") if hasattr(row, "get") else None
    return int(epoch) if isinstance(epoch, (int, float)) else None


def context_used_pct(remaining_pct: Optional[float]) -> Optional[float]:
    if remaining_pct is None:
        return None
    return round(min(100.0, max(0.0, 100.0 - float(remaining_pct))), 1)


def _model_facts_for_one(
    name: str,
    *,
    agent_family: str,
    epoch: Optional[int],
    instance_index: Optional[Any],
    conversation_for_instance: Callable[..., Any],
    read_usage: Callable[..., Any],
    projects_dir: Optional[Path],
    codex_home: Optional[str],
) -> ModelListingFacts:
    uuid, working_dir = conversation_for_instance(instance_index, name, epoch)
    if not uuid:
        return ModelListingFacts(family=agent_family)
    subject = SessionSubject(
        agent_family=agent_family, conversation_uuid=uuid, working_dir=working_dir
    )
    usage = read_usage(
        subject,
        projects_dir=projects_dir,
        codex_home=codex_home,
        max_cold_bytes=MAX_COLD_TRANSCRIPT_BYTES,
    )
    if usage.state != "ok":
        return ModelListingFacts(family=agent_family)
    return ModelListingFacts(
        model=usage.model,
        model_effort=usage.effort,
        model_tier=usage.model_cost_tier,
        family=agent_family,
        context_used_pct=context_used_pct(usage.context_remaining_pct),
    )


def build_model_listing_prefetch(
    *,
    names: Iterable[Optional[str]],
    status_map: Optional[Any],
    instance_index: Optional[Any],
    prefetch: Optional[Any],
    projects_dir: Optional[Path] = None,
    codex_home: Optional[str] = None,
    conversation_for_instance: Optional[Callable[..., Any]] = None,
    read_usage: Optional[Callable[..., Any]] = None,
) -> Dict[str, ModelListingFacts]:
    if conversation_for_instance is None:
        from src.core.listing_attention import (
            conversation_for_instance as _conversation_for_instance,
        )

        conversation_for_instance = _conversation_for_instance
    if read_usage is None:
        read_usage = read_session_token_usage

    out: Dict[str, ModelListingFacts] = {}
    for name in names:
        if not name or name in out:
            continue
        agent_family = _stored_agent_family(name, prefetch=prefetch)
        if agent_family not in _FAMILIES_WITH_READER:
            out[name] = ModelListingFacts(family=agent_family)
            continue
        try:
            epoch = _epoch_for_name(name, status_map=status_map)
            out[name] = _model_facts_for_one(
                name,
                agent_family=agent_family,
                epoch=epoch,
                instance_index=instance_index,
                conversation_for_instance=conversation_for_instance,
                read_usage=read_usage,
                projects_dir=projects_dir,
                codex_home=codex_home,
            )
        except Exception:  # noqa: BLE001
            out[name] = ModelListingFacts(family=agent_family)
    return out


class ModelListingPrefetch:

    def __init__(self, by_name: Optional[Mapping[str, ModelListingFacts]] = None) -> None:
        self.by_name: Mapping[str, ModelListingFacts] = dict(by_name or {})

    def has(self, tmux_name: Optional[str]) -> bool:
        return bool(tmux_name) and tmux_name in self.by_name

    def facts_for(self, tmux_name: Optional[str]) -> ModelListingFacts:
        return self.by_name.get(tmux_name or "", _UNKNOWN)
