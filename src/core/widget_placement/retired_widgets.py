
from __future__ import annotations

from typing import Any, Dict, List, Optional

RETIRED_WIDGETS: Dict[str, str] = {"core.approvals": "core.questions"}

RENAMED_WIDGETS: Dict[str, str] = {
    "core.huddle": "core.task-manager-mk2",
    "core.huddle-all": "core.task-manager-mk2-all",
    "core.huddle-list": "core.task-manager-mk2",
    "core.task-manager": "core.task-manager-mk2",
    "core.task-manager-all": "core.task-manager-mk2-all",
    "core.task-list": "core.task-manager-mk2",
}

_OPTIONLESS_SUCCESSOR = frozenset({"core.huddle-list", "core.task-list"})

PLACEMENT_FIELDS = ("drawer_zone", "session_rail", "session_rail_bottom")

_APPROVALS_ONLY_OPTIONS = {"kind_all": False, "kind_huddle": False, "kind_automations": False}


def approvals_only_options() -> Dict[str, bool]:
    return dict(_APPROVALS_ONLY_OPTIONS)


def _items_of(container: Dict[str, Any]) -> List[List[Any]]:
    lists = [container["items"]] if isinstance(container.get("items"), list) else []
    for section in container.get("sections") or []:
        if isinstance(section, dict) and isinstance(section.get("items"), list):
            lists.append(section["items"])
    return lists


def _free_instance(taken: set) -> str:
    number = 2
    while f"i{number}" in taken:
        number += 1
    return f"i{number}"


def _migrate_container(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    lists = _items_of(value)
    if not any(isinstance(i, dict) and i.get("widget") in RETIRED_WIDGETS for items in lists for i in items):
        return _migrate_glance(value)
    taken = {i.get("instance") for items in lists for i in items if isinstance(i, dict) and i.get("widget") == "core.questions"}
    migrated: Dict[str, Any] = dict(value)

    def rewrite(items: List[Any]) -> List[Any]:
        out = []
        for item in items:
            if isinstance(item, dict) and item.get("widget") in RETIRED_WIDGETS:
                item = {**item, "widget": RETIRED_WIDGETS[item["widget"]], "options": approvals_only_options()}
                item.pop("view", None)
                if item.get("instance") in taken or (None in taken and item.get("instance") is None):
                    item["instance"] = _free_instance({t for t in taken if t})
                taken.add(item.get("instance"))
            out.append(item)
        return out

    if isinstance(value.get("items"), list):
        migrated["items"] = rewrite(value["items"])
    if isinstance(value.get("sections"), list):
        migrated["sections"] = [
            {**s, "items": rewrite(s["items"])} if isinstance(s, dict) and isinstance(s.get("items"), list) else s
            for s in value["sections"]
        ]
    return _migrate_glance(migrated)


def _migrate_glance(value: Dict[str, Any]) -> Dict[str, Any]:
    glance = value.get("glance")
    if not isinstance(glance, list) or not any(isinstance(g, dict) and g.get("widget") in RETIRED_WIDGETS for g in glance):
        return value
    return {
        **value,
        "glance": [
            {**g, "widget": RETIRED_WIDGETS[g["widget"]]}
            if isinstance(g, dict) and g.get("widget") in RETIRED_WIDGETS
            else g
            for g in glance
        ],
    }


HEADER_OPTION = "show_header"


def _renamed_item(item: Dict[str, Any], *, keep_header: bool) -> Dict[str, Any]:
    out = {**item, "widget": RENAMED_WIDGETS[item["widget"]]}
    if item["widget"] in _OPTIONLESS_SUCCESSOR:
        old = item.get("options") if isinstance(item.get("options"), dict) else {}
        out.pop("options", None)
        if keep_header:
            shown = old.get(HEADER_OPTION)
            out["options"] = {HEADER_OPTION: shown if isinstance(shown, bool) else True}
    return out


def _held_widgets(container: Dict[str, Any]) -> set:
    return {
        i.get("widget")
        for i in (container["items"] if isinstance(container.get("items"), list) else [])
        if isinstance(i, dict)
    } | {
        i.get("widget")
        for s in container.get("sections") or []
        if isinstance(s, dict) and isinstance(s.get("items"), list)
        for i in s["items"]
        if isinstance(i, dict)
    }


def _rename_items(items: List[Any], held: Optional[set]) -> List[Any]:
    if not any(isinstance(i, dict) and i.get("widget") in RENAMED_WIDGETS for i in items):
        return items
    out: List[Any] = []
    for item in items:
        if isinstance(item, dict) and item.get("widget") in RENAMED_WIDGETS:
            if held is not None:
                if RENAMED_WIDGETS[item["widget"]] in held:
                    continue
                held.add(RENAMED_WIDGETS[item["widget"]])
            item = _renamed_item(item, keep_header=held is not None)
        out.append(item)
    return out


def _rename_container(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    held = {w for w in _held_widgets(value) if w not in RENAMED_WIDGETS}
    out = value
    for key, taken in (("items", held), ("glance", None)):
        if isinstance(value.get(key), list):
            renamed = _rename_items(value[key], taken)
            if renamed is not value[key]:
                out = {**out, key: renamed}
    if isinstance(value.get("sections"), list):
        sections = [{**s, "items": _rename_items(s["items"], held)} if isinstance(s, dict) and isinstance(s.get("items"), list) else s for s in value["sections"]]
        if any(new is not old and new != old for new, old in zip(sections, value["sections"])):
            out = {**out, "sections": sections}
    return out


def migrate_retired_placements(values: Dict[str, Any]) -> Dict[str, Any]:
    changed: Optional[Dict[str, Any]] = None
    for name in PLACEMENT_FIELDS:
        if name in values:
            new = _migrate_container(_rename_container(values[name]))
            if new is not values[name]:
                changed = changed if changed is not None else dict(values)
                changed[name] = new
    return changed if changed is not None else values
