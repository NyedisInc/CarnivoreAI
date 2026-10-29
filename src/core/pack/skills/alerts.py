
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import structlog

from src.core.app_alerts import constants as K
from src.core.app_alerts import service
from src.core.pack.skills.receiver import ReceiverState

logger = structlog.get_logger()

SOURCE = "pack_skills"
ALPHA_KEY = "pack_skills.alpha_changed"
PLACER_PREFIX = "pack_skills.placer_gone:"
EDIT_PREFIX = "pack_skills.edit_replaced:"
EDITS_PREFIX = "pack_skills.edits_replaced:"
REFUSED_PREFIX = "pack_skills.settings_refused:"
LOCAL_EDIT, REMOTE_MERGE = "local_edit", "remote_merge"
MAX_SINGLE = 3
THIS_COMPUTER = "this computer"
_T = "app_alert.pack_skills."

Settings = tuple[str, str, int]


@dataclass(frozen=True)
class Seams:

    install_id: str
    settings: Callable[[], Settings]
    label_of: Callable[[str], str]
    grant_live: Callable[[str], bool]


_SEAMS: Optional[Seams] = None


def configure(seams: Optional[Seams]) -> None:
    global _SEAMS
    _SEAMS = seams


def label_for(data: Mapping[str, Any], install_id: str) -> str:
    labels = data.get("labels")
    return (labels.get(install_id) if isinstance(labels, dict) else None) or install_id[:8]


def _label(data: dict[str, Any], seams: Seams, install_id: str) -> str:
    if install_id == seams.install_id:
        return THIS_COMPUTER
    live = seams.label_of(install_id)
    if live:
        data.setdefault("labels", {})[install_id] = live
    return live or label_for(data, install_id)


def check_alpha(state: ReceiverState, source: str, from_install_id: str = "") -> None:
    seams = _SEAMS
    if seams is None:
        return
    master, setter, counter = seams.settings()
    if not master:
        return
    with state.lock:
        data = state.load()
        marks = data.setdefault("alerted", {})
        seen = marks.get("alpha_seen")
        if seen == master:
            return
        if seen is not None and source != LOCAL_EDIT:
            params = {"new": _label(data, seams, master), "old": _label(data, seams, seen),
                      "claimed": "pairing" if counter == 0 else _label(data, seams, setter),
                      "sender": _label(data, seams, from_install_id) if from_install_id else THIS_COMPUTER}
            actions = [{"id": "open_pack_skills", "label_key": f"{_T}action.open", "href": "#skills"},
                       {"id": "make_alpha_again", "label_key": f"{_T}action.make_alpha_again", "method": "PUT",
                        "route": "/pack/master", "body": {"machine": seen}}]
            row = service.raise_alert(ALPHA_KEY, source=SOURCE, severity=K.SEV_WARN, title_key=f"{_T}alpha_changed.title",
                                      detail_key=f"{_T}alpha_changed.detail", params=params, auto_resolve=False, actions=actions)
            if row is None:
                return
        marks["alpha_seen"] = master
        state.save(data)


def check_placers(state: ReceiverState) -> None:
    """Raise one alert per computer that placed skills here and no longer holds a live grant; clear it when that computer is paired
    again or nothing it placed is left. Blocking. Example: check_placers(state) -> ``pack_skills.placer_gone:iid-hosta`` raised once."""
    seams = _SEAMS
    if seams is None:
        return
    with state.lock:
        data = state.load()
        marks = data.setdefault("alerted", {}).setdefault("placer", {})
        placed: dict[str, set[tuple[Any, Any]]] = {}
        for row in data.get("applied", []):
            who = row.get("alpha")
            if row.get("placed") is True and isinstance(who, str) and who and who != seams.install_id:
                placed.setdefault(who, set()).add((row.get("family"), row.get("name")))
        before = repr((data.get("labels"), marks))
        for who in sorted(set(placed) | set(marks)):
            live = seams.grant_live(who)
            label = _label(data, seams, who) if who in placed else label_for(data, who)
            if who in placed and not live and who not in marks:
                n = len(placed[who])
                actions = [{"id": "open_pack_skills", "label_key": f"{_T}action.open", "href": "#skills"},
                           {"id": "remove_placed", "label_key": f"{_T}action.remove_placed", "explain_key": f"{_T}placer_gone.explain",
                            "actions": [{"id": "trash_placed", "label_key": f"{_T}action.trash_placed", "method": "POST",
                                         "route": "/pack/skills/trash-placed", "body": {"from_install_id": who}, "tone": "danger"}]}]
                row = service.raise_alert(PLACER_PREFIX + who, source=SOURCE, severity=K.SEV_WARN, title_key=f"{_T}placer_gone.title",
                                          detail_key=f"{_T}placer_gone.detail", params={"label": label, "count": n}, auto_resolve=True,
                                          actions=actions)
                if row is not None:
                    marks[who] = True
            elif who in marks and (who not in placed or live):
                marks.pop(who, None)
                service.resolve(PLACER_PREFIX + who)
        if repr((data.get("labels"), marks)) != before:
            state.save(data)


def replaced(items: Sequence[tuple[str, str, str]], alpha_id: str, gen: int) -> None:
    seams = _SEAMS
    if seams is None or not items:
        return
    alpha = seams.label_of(alpha_id) or alpha_id[:8]
    if len(items) > MAX_SINGLE:
        service.raise_alert(f"{EDITS_PREFIX}{gen}", source=SOURCE, severity=K.SEV_INFO, title_key=f"{_T}edits_replaced.title",
                            detail_key=f"{_T}edit_replaced.detail", auto_resolve=False,
                            params={"count": len(items), "alpha": alpha, "folder": str(Path(items[0][2]).parent)})
        return
    for family, name, path in items:
        service.raise_alert(f"{EDIT_PREFIX}{family}:{name}:{Path(path).name}", source=SOURCE, severity=K.SEV_INFO,
                            title_key=f"{_T}edit_replaced.title", detail_key=f"{_T}edit_replaced.detail", auto_resolve=False,
                            params={"name": name, "alpha": alpha, "folder": str(Path(path).parent)})


def settings_refused_hook(sender: str, verdict: Any, doc: Any) -> None:
    settings_refused(sender, verdict.outcome, str(doc.rev[1]), doc.master_install_id)


def settings_refused(sender: str, outcome: str, signer: str, named_master: str) -> None:
    seams = _SEAMS
    if seams is None:
        return
    held = seams.settings()[0]
    if named_master == held:
        return
    params = {"sender": seams.label_of(sender) or sender[:8], "signer": seams.label_of(signer) or signer[:8],
              "named": THIS_COMPUTER if named_master == seams.install_id else (seams.label_of(named_master) or named_master[:8]),
              "held": THIS_COMPUTER if held == seams.install_id else (seams.label_of(held) or held[:8])}
    actions = [{"id": "open_pack", "label_key": f"{_T}action.open_pack", "href": "#pack"}]
    detail = outcome if outcome in ("not_alpha", "unsigned", "unpinned") else "bad_signature"
    service.raise_alert(REFUSED_PREFIX + sender, source=SOURCE, severity=K.SEV_WARN, title_key=f"{_T}settings_refused.title",
                        detail_key=f"{_T}settings_refused.detail.{detail}", params=params, auto_resolve=False, actions=actions)
