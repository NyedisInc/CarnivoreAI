
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class NameReads:

    label: Optional[str] = None
    identity: Optional[dict] = None
    registry: Optional[Any] = None
    transcript: Optional[Any] = None


@dataclass(frozen=True)
class ListingPrefetch:

    by_name: Mapping[str, NameReads] = field(default_factory=dict)

    def has(self, tmux_name: Optional[str]) -> bool:
        return bool(tmux_name) and tmux_name in self.by_name

    def label_for(self, tmux_name: Optional[str]) -> Optional[str]:
        entry = self.by_name.get(tmux_name or "")
        return entry.label if entry is not None else None

    def identity_for(self, tmux_name: Optional[str]) -> Optional[dict]:
        entry = self.by_name.get(tmux_name or "")
        return entry.identity if entry is not None else None

    def registry_for(self, tmux_name: Optional[str]) -> Optional[Any]:
        entry = self.by_name.get(tmux_name or "")
        return entry.registry if entry is not None else None

    def transcript_for(self, tmux_name: Optional[str]) -> Optional[Any]:
        entry = self.by_name.get(tmux_name or "")
        return entry.transcript if entry is not None else None


def build_listing_prefetch(
    *,
    names: Iterable[Optional[str]],
    label_for_name: Callable[[Optional[str]], Optional[str]],
    identity_for_live_name: Callable[[Optional[str]], Optional[dict]],
    attention_for_name: Optional[
        Callable[[str], Tuple[Any, Any]]
    ] = None,
    label_identity_for_names: Optional[
        Callable[[Sequence[str]], Mapping[str, Tuple[Optional[str], Optional[dict]]]]
    ] = None,
) -> ListingPrefetch:
    by_name: Dict[str, NameReads] = {}
    unique = [n for n in dict.fromkeys(names) if n]
    batched = label_identity_for_names(unique) if label_identity_for_names and unique else {}
    for name in unique:
        if name in by_name:
            continue
        registry = None
        transcript = None
        if attention_for_name is not None:
            registry, transcript = attention_for_name(name)
        label, identity = batched[name] if name in batched else (
            label_for_name(name), identity_for_live_name(name))
        by_name[name] = NameReads(
            label=label,
            identity=identity,
            registry=registry,
            transcript=transcript,
        )
    return ListingPrefetch(by_name=by_name)
