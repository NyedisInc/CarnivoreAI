
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from src.cplugs.huddle import item_owner, owner_read, rules, service, title
from src.cplugs.sdk import CplugContext, ports

NAME = "huddle.devtools"
MAX_ROWS = 200
TAG_ANY, TAG_NONE = "any", "none"
SHARED_NAME = "all"


def _same(a: Any, b: Any) -> bool:
    return str(a).strip().casefold() == str(b).strip().casefold()


def _tag_of(item: Dict[str, Any]) -> str:
    return str(item.get(item_owner.TAGGED_BY) or item.get(item_owner.TAG_COLUMN) or "")


class DevToolsPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    async def _lists(self) -> List[Dict[str, Any]]:
        body = await asyncio.to_thread(service.store(self._ctx).aggregate)
        names = await asyncio.to_thread(service.project_names, self._ctx)
        held = service.aggregate_groups(body, names)
        known = {g["list"] for g in held}
        empty = [{"list": key, "name": name, "project_id": None, "revision": 0, "groups": [], "items": []} for key, name in sorted(names.items()) if key not in known]
        return held + empty

    @staticmethod
    def _list_named(lists: List[Dict[str, Any]], value: str) -> Optional[Dict[str, Any]]:
        for entry in lists:
            if value == entry["list"] or (entry["name"] and _same(entry["name"], value)) or (entry["list"] == rules.ALL_LIST and _same(value, SHARED_NAME)):
                return entry
        return None

    async def projects(self) -> List[Dict[str, Any]]:
        out = []
        for entry in await self._lists():
            counts: Dict[str, int] = {}
            for item in entry["items"]:
                name = rules.DONE if item["state"] in rules.APPROVED_STATES else item["status"]
                counts[name] = counts.get(name, 0) + 1
            out.append({"list": entry["list"], "project": entry["name"] or SHARED_NAME, "counts": counts,
                        "open_tasks": sum(n for s, n in counts.items() if s != rules.DONE)})
        return out

    async def tasks(self, *, project: Optional[str] = None, status: Optional[str] = None, group: Optional[str] = None,
                    tag: Optional[str] = None, kind: Optional[str] = None) -> Dict[str, Any]:
        lists = await self._lists()
        picked = lists
        if project is not None:
            one = self._list_named(lists, project)
            if one is None:
                return {"error": f"no project {project!r}; call with view=projects to see them"}
            picked = [one]
        items = [(e, i) for e in picked for i in e["items"]]
        await owner_read.annotate_tagged(self._ctx, [i for _e, i in items])
        rows = []
        for entry, item in items:
            if not self._wanted(entry, item, status, group, tag, kind):
                continue
            names = {g["id"]: g["name"] for g in entry.get("groups", [])}
            row = {"id": item["id"], "title": title.display(item), "status": item["status"], "project": entry["name"] or SHARED_NAME,
                   "group": names.get(item.get("group"), ""), "tag": _tag_of(item)}
            if item.get("kind"):
                row["kind"] = item["kind"]
            rows.append(row)
        return {"total": len(rows), "shown": min(len(rows), MAX_ROWS), "rows": rows[:MAX_ROWS]}

    @staticmethod
    def _wanted(entry: Dict[str, Any], item: Dict[str, Any], status: Optional[str], group: Optional[str], tag: Optional[str], kind: Optional[str]) -> bool:
        if status is None:
            if item["state"] in rules.APPROVED_STATES:
                return False
        elif not any(_same(item.get(field, ""), status) for field in ("status", "section", "state")):
            return False
        if group is not None:
            names = {g["id"]: g["name"] for g in entry.get("groups", [])}
            if not (_same(names.get(item.get("group"), ""), group) or str(item.get("group")) == str(group)):
                return False
        if tag is not None:
            have = _tag_of(item)
            if not (bool(have) if tag == TAG_ANY else not have if tag == TAG_NONE else _same(have, tag) or _same(item.get(item_owner.TAG_COLUMN, ""), tag)):
                return False
        return kind is None or _same(item.get("kind", ""), kind)

    async def resolve(self, *, project: Optional[str] = None, groups: Optional[List[str]] = None, items: Optional[List[int]] = None) -> Dict[str, Any]:
        lists = await self._lists()
        one = None
        if project is not None:
            one = self._list_named(lists, project)
            if one is None:
                return {"error": f"no project {project!r}"}
        found: List[int] = []
        for want in groups or []:
            hit = [g["id"] for e in ([one] if one else lists) for g in e.get("groups", []) if _same(g["name"], want) or str(g["id"]) == str(want)]
            if not hit:
                return {"error": f"no group {want!r}" + (f" in project {project!r}" if one else "")}
            found += hit
        live = {i["id"] for e in lists for i in e["items"]}
        missing = [i for i in items or [] if i not in live]
        if missing:
            return {"error": f"no task {missing[0]}"}
        return {"list": one["list"] if one else None, "project": (one["name"] or SHARED_NAME) if one else None,
                "groups": sorted(set(found)), "items": list(items or [])}


def register(ctx: CplugContext) -> None:
    ports.register(NAME, DevToolsPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)
