
from __future__ import annotations

import re
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


def corner_legacy(doc: Mapping[str, Any], type_id: str) -> bool:
    return doc_model.effective_value(doc, doc_model.corner_key(type_id), True) is not False


def corner(doc: Mapping[str, Any], type_id: str) -> bool:
    from src.core.notifications.settings_doc import routes  # noqa: PLC0415

    if not routes.master_on(doc, type_id):
        return False
    me = doc_model.self_iid(doc)
    if me is not None:
        path = doc_model.route_path(me, "corner", type_id)
        if doc_model.effective_source(doc, path) != "absent":
            return doc_model.effective_value(doc, path, True) is not False
    return corner_legacy(doc, type_id)


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

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        iid = doc_model.self_iid(doc)
        if iid is None:
            return doc_model.set_local(doc, doc_model.corner_key(type_id), bool(value))
        return doc_model.set_global(doc, doc_model.route_path(iid, "corner", type_id), bool(value), me)

    return store.update(mutate)


SESSION_NAME = re.compile(r"^[A-Za-z0-9_.@:+-]{1,200}$")
_SESSION_PREFIX = "ssound."


def session_key(tmux_name: str, type_id: str) -> str:
    if not SESSION_NAME.match(tmux_name or ""):
        raise doc_model.SettingsValueError("bad session name")
    return doc_model.local_key(f"{_SESSION_PREFIX}{doc_model._check_type(type_id)}|{tmux_name}")


def session_sound(doc: Mapping[str, Any], tmux_name: str, type_id: str) -> Optional[str]:
    try:
        val = doc_model.effective_value(doc, session_key(tmux_name, type_id), None)
    except ValueError:
        return None
    return val if val in card_contract.SOUNDS else None


def session_sounds(doc: Mapping[str, Any], tmux_name: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    suffix = f"|{tmux_name}"
    for path, val in doc["local"].items():
        body = path[len(doc_model.LOCAL_PREFIX):] if path.startswith(doc_model.LOCAL_PREFIX) else ""
        if body.startswith(_SESSION_PREFIX) and body.endswith(suffix) and val in card_contract.SOUNDS:
            out[body[len(_SESSION_PREFIX):-len(suffix)]] = val
    return out


def put_session_sound(store: SettingsDocStore, tmux_name: str, type_id: str, sound: Optional[str]) -> Doc:
    type_id = types.canonical(type_id)
    key = session_key(tmux_name, type_id)
    if sound is None:
        return store.update(lambda d, me: doc_model.clear_local(d, key))
    if sound not in card_contract.SOUNDS:
        raise doc_model.SettingsValueError("bad sound")
    return store.update(lambda d, me: doc_model.set_local(d, key, sound))
