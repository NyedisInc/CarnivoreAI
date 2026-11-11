
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from src.core.notifications import card_contract
from src.core.notifications.settings_doc import styles_store

_doc_source: Optional[Callable[[], Mapping[str, Any]]] = None


def install_source(source: Optional[Callable[[], Mapping[str, Any]]]) -> None:
    global _doc_source
    _doc_source = source


@dataclass(frozen=True)
class Style:

    sound: str
    level: str


def default_style(type_id: str) -> Style:
    sound, level = card_contract.KIND_STYLE[card_contract.kind_for_type(type_id)]
    return Style(sound=sound, level=level)


def effective_style_in(doc: Mapping[str, Any], type_id: str) -> Style:
    try:
        mine = styles_store.stored(doc, type_id)
    except ValueError:
        mine = None
    if mine is None:
        return default_style(type_id)
    return Style(sound=mine["sound"], level=styles_store.URGENCIES[mine["urgency"]])


def effective_style(type_id: str) -> Style:
    source = _doc_source
    return effective_style_in(source(), type_id) if source is not None else default_style(type_id)
