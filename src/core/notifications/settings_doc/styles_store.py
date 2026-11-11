
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from src.core.notifications import card_contract, doc_model, types
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore

URGENCIES: Dict[str, str] = {name: letter for letter, name in card_contract.LEVELS.items()}


def clean(raw: Any) -> Optional[Dict[str, str]]:
    if not isinstance(raw, Mapping) or set(raw) != {"sound", "urgency"}:
        return None
    sound, urgency = raw["sound"], raw["urgency"]
    if sound not in card_contract.SOUNDS or urgency not in URGENCIES:
        return None
    return {"sound": sound, "urgency": urgency}


def stored(doc: Mapping[str, Any], type_id: str) -> Optional[Dict[str, str]]:
    return clean(doc_model.effective_value(doc, doc_model.style_path(type_id), None))


def corner(doc: Mapping[str, Any], type_id: str) -> bool:
    return doc_model.effective_value(doc, doc_model.corner_key(type_id), True) is not False


def put_style(store: SettingsDocStore, type_id: str, sound: Optional[str], urgency: Optional[str]) -> Doc:
    type_id = types.canonical(type_id)
    if not types.is_registered(type_id):
        raise ValueError(f"not a notification type: {type_id!r}")
    if sound is not None and sound not in card_contract.SOUNDS:
        raise ValueError("bad sound")
    if urgency is not None and urgency not in URGENCIES:
        raise ValueError("bad urgency")

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        from src.core.notifications import styles
        base = styles.effective_style_in(doc, type_id)
        new = {"sound": sound or base.sound, "urgency": urgency or card_contract.LEVELS[base.level]}
        return doc_model.set_global(doc, doc_model.style_path(type_id), new, me)

    return store.update(mutate)


def put_corner(store: SettingsDocStore, type_id: str, value: bool) -> Doc:
    type_id = types.canonical(type_id)
    if not types.is_registered(type_id):
        raise ValueError(f"not a notification type: {type_id!r}")
    return store.update(lambda d, me: doc_model.set_local(d, doc_model.corner_key(type_id), bool(value)))
