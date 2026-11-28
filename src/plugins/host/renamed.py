
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable, Collection, FrozenSet, Iterable, List, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.routing import APIRoute

from src.core.app_alerts import constants as alert_const
from src.plugins.host import identity, renamed_entry, state as owner_state
from src.plugins.sdk import old_names
from src.plugins.sdk.definition import CplugDefinition
from src.plugins.sdk.routing import mirror_public_route

logger = structlog.get_logger()


ALERT_SOURCE = "cplug_rename"
_T = "app_alert.cplug_rename.held."
_T_STUCK = "app_alert.cplug_rename.stuck."


class RenamedFromRefused(ValueError):
    pass


def check_reserved(cplug_id: str, old: str) -> None:
    if old in identity.HOST_WORDS:
        raise RenamedFromRefused(f"{cplug_id}: renamed_from {old} is a host word, never a plugin id")
    if old not in identity.ROADMAP_IDS | identity.RETIRED_IDS:
        raise RenamedFromRefused(f"{cplug_id}: renamed_from {old} must be reserved forever: add it to identity.RETIRED_IDS")


def old_ids(defs: Iterable[CplugDefinition]) -> FrozenSet[str]:
    return frozenset(d.manifest.renamed_from for d in defs if d.manifest.renamed_from)


def canonical(defs: Iterable[CplugDefinition], cplug_id: str) -> str:
    defs = tuple(defs)
    if any(d.id == cplug_id for d in defs):
        return cplug_id
    return next((d.id for d in defs if cplug_id and d.manifest.renamed_from == cplug_id), cplug_id)


def alert_shadowed_installs(state_dir: Path, defs: Iterable[CplugDefinition], sink: Callable[..., Any]) -> List[str]:
    renamed_to = {d.manifest.renamed_from: d.id for d in defs if d.manifest.renamed_from}
    if not renamed_to:
        return []
    try:
        held = sorted(r.name for r in identity.installs(state_dir) if r.name in renamed_to)
    except identity.LedgerUnreadable:
        logger.warning("cplug_renamed_ledger_unreadable")
        return []
    for name in held:
        logger.warning("cplug_renamed_id_held_by_install", name=name, plugin=renamed_to[name])
        sink(f"{ALERT_SOURCE}.held.{name}", source=ALERT_SOURCE, severity=alert_const.SEV_WARN, title_key=f"{_T}title",
             detail_key=f"{_T}detail", params={"name": name, "plugin": renamed_to[name]}, sticky=True, auto_resolve=False)
    return held


def alert_stuck_carries(state_dir: Path, defs: Iterable[CplugDefinition], sink: Callable[..., Any]) -> List[str]:
    stuck: List[str] = []
    for definition in defs:
        reason = owner_state.carry_state(state_dir, definition.manifest)
        if not reason:
            continue
        stuck.append(definition.id)
        logger.error("cplug_renamed_entry_stuck", plugin=definition.id, old=definition.manifest.renamed_from, reason=reason)
        sink(f"{ALERT_SOURCE}.stuck.{definition.id}", source=ALERT_SOURCE, severity=alert_const.SEV_WARN, title_key=f"{_T_STUCK}title",
             detail_key=f"{_T_STUCK}detail_{reason}", params={"name": definition.manifest.renamed_from, "plugin": definition.id}, sticky=True, auto_resolve=False)
    return stuck


def resolve_requires(defs: Iterable[CplugDefinition]) -> Tuple[CplugDefinition, ...]:
    defs = tuple(defs)
    new_id = {d.manifest.renamed_from: d.id for d in defs if d.manifest.renamed_from}
    out = []
    for d in defs:
        requires = tuple(new_id.get(r, r) for r in d.manifest.requires)
        if requires == d.manifest.requires:
            out.append(d)
            continue
        logger.info("cplug_requires_renamed", cplug=d.id, requires=list(requires))
        out.append(dataclasses.replace(d, manifest=dataclasses.replace(d.manifest, requires=requires)))
    return tuple(out)


def old_prefix(d: CplugDefinition) -> str:
    head = f"/cplugs/{d.id}"
    own = d.router.prefix if d.router is not None else head
    return f"/cplugs/{d.manifest.renamed_from}{own[len(head):]}" if own.startswith(head) else ""


def _counter(old_path: str, methods: Collection[str]) -> Callable[[Request], Any]:
    first = sorted(methods)[0]

    async def count(request: Request) -> None:
        method = request.method if request.method in methods else first
        old_names.note(old_names.KIND_ROUTE, f"{method} {old_path}")

    return count


def _alias(router: APIRouter, route: APIRoute, old_path: str) -> None:
    router.add_api_route(
        old_path, route.endpoint, response_model=route.response_model, status_code=route.status_code, tags=list(route.tags),
        dependencies=[*route.dependencies, Depends(_counter(old_path, route.methods))], summary=route.summary,
        description=route.description, response_description=route.response_description, responses=dict(route.responses),
        deprecated=route.deprecated, methods=sorted(route.methods), response_model_include=route.response_model_include,
        response_model_exclude=route.response_model_exclude, response_model_by_alias=route.response_model_by_alias,
        response_model_exclude_unset=route.response_model_exclude_unset,
        response_model_exclude_defaults=route.response_model_exclude_defaults,
        response_model_exclude_none=route.response_model_exclude_none, include_in_schema=False, response_class=route.response_class,
        name=route.name, callbacks=route.callbacks, openapi_extra=route.openapi_extra,
        generate_unique_id_function=route.generate_unique_id_function, route_class_override=type(route),
        strict_content_type=route.strict_content_type)


def alias_router(d: CplugDefinition) -> Optional[APIRouter]:
    if not d.manifest.renamed_from or d.router is None:
        return None
    new_prefix, before = d.router.prefix, old_prefix(d)
    router = APIRouter()
    names: List[str] = []
    for route in d.router.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(new_prefix):
            logger.warning("cplug_renamed_route_skipped", cplug=d.id, path=str(getattr(route, "path", "")))
            continue
        old_path = before + route.path[len(new_prefix):]
        _alias(router, route, old_path)
        for method in sorted(route.methods):
            mirror_public_route(method, route.path, old_path)
            names.append(f"{method} {old_path}")
    old_names.declare(old_names.KIND_ROUTE, names)
    return router


def prefix_table_gaps(defs: Iterable[CplugDefinition], paths: Iterable[str]) -> List[str]:
    rows = list(paths)
    have = set(rows)
    gaps: List[str] = []
    for d in defs:
        old = d.manifest.renamed_from
        if not old:
            continue
        for a, b in ((f"/cplugs/{d.id}", f"/cplugs/{old}"), (f"/cplugs/{old}", f"/cplugs/{d.id}")):
            for row in rows:
                at = row.find(a)
                if at < 0 or row[at + len(a):at + len(a) + 1] not in ("", "/"):
                    continue
                twin = row[:at] + b + row[at + len(a):]
                if twin not in have:
                    gaps.append(f"{row} needs {twin}")
    return gaps
