
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core.pack.errors.input_error import PackInputError
from src.core.pack.jobs import recipe, snapshot
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import DepDir, JobRequest
from src.core.pack.placement import needs as needs_mod, workload
from src.core.pack.placement.needs import Need

KINDS: Tuple[str, ...] = (*workload.HEAVY_KINDS, workload.KIND_SESSION)
MAX_WORDS = 8


@dataclass(frozen=True)
class Asks:

    strict: Tuple[Need, ...] = ()
    filters: Tuple[Need, ...] = ()
    prefer: Tuple[Need, ...] = ()

    @property
    def hard(self) -> List[str]:
        return list(dict.fromkeys(n.text for n in (*self.strict, *self.filters)))


def get(store: JobStore, project_uid: str, kind: str) -> Tuple[List[str], List[str]]:
    return store.needs_rows(project_uid).get(kind, ([], []))


def stored(store: JobStore, project_uid: str, kind: str) -> Optional[Tuple[List[str], List[str]]]:
    return store.needs_rows(project_uid).get(kind)


def put(store: JobStore, project_uid: str, doc: Dict[str, Any]) -> None:
    if not isinstance(doc, dict):
        raise PackInputError("send an object of kinds")
    writes: Dict[str, Optional[Tuple[List[str], List[str]]]] = {}
    for kind, value in doc.items():
        if kind not in KINDS:
            raise PackInputError(f"kind must be one of {', '.join(KINDS)}")
        if value is None:
            writes[kind] = None
            continue
        if not isinstance(value, dict) or set(value) - {"needs", "prefer"}:
            raise PackInputError("each kind takes only needs and prefer")
        writes[kind] = tuple(  # type: ignore[assignment]
            [n.text for n in needs_mod.parse_all(value.get(key) or [], limit=MAX_WORDS)] for key in ("needs", "prefer"))
    store.needs_replace(project_uid, writes)


def setup_filters(roots: Sequence[str], setup: Optional[Sequence[str]], air_gap: bool) -> List[Need]:
    deps: Dict[str, DepDir] = {}
    for root in dict.fromkeys(roots):
        for dep in snapshot.dep_dirs_of(root):
            deps.setdefault(dep.path, dep)
    steps = recipe.plan("/slot", list(deps.values()), {}, setup, air_gap=air_gap)
    return needs_mod.parse_all(recipe.tools_needed(steps), limit=MAX_WORDS)


def merge(store: JobStore, project_uid: str, req: JobRequest, setup_needs: Sequence[Need] = ()) -> Asks:
    own = stored(store, project_uid, req.kind)
    command_strict, command_filters, command_prefer = needs_mod.from_command(req.command or "")
    if own is None:
        default_filters, default_prefer = needs_mod.kind_defaults(req.kind)
        project_strict: List[Need] = []
        project_prefer: List[Need] = []
    else:
        default_filters, default_prefer = [], []
        project_strict, project_prefer = needs_mod.parse_all(own[0], limit=MAX_WORDS), needs_mod.parse_all(own[1], limit=MAX_WORDS)
    strict = needs_mod.parse_all(req.needs) + project_strict + command_strict
    prefer = needs_mod.parse_all(req.prefer) + project_prefer + command_prefer + default_prefer
    return Asks(tuple(dict.fromkeys(strict)), tuple(dict.fromkeys([*command_filters, *default_filters, *setup_needs])), tuple(dict.fromkeys(prefer)))
