
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Tuple

from src.core.inventory.model import REPORT, SCOPE_PROJECT, SCOPE_SESSION
from src.core.inventory.scope import Scope

GENERIC = "generic"
BESPOKE = "bespoke"

UNKEYED = "unkeyed"
GLOBAL = "global"
SECRET = "secret"
TRANSIENT = "transient"
DORMANT = "dormant"
SHARED = "shared"
SHADOW = "shadow"
DERIVED = "derived"
GAP = "gap"
EXCLUSION_KINDS = (UNKEYED, GLOBAL, SECRET, TRANSIENT, DORMANT, SHARED, SHADOW, DERIVED, GAP)

Where = Optional[Tuple[str, List[Any]]]
WhereFn = Callable[[Scope, "ClaimBook"], Where]


@dataclass(frozen=True)
class Claim:

    store: str
    table: str
    scopes: Tuple[str, ...] = (SCOPE_SESSION,)
    where: Optional[WhereFn] = None
    handler: str = GENERIC
    keys: Tuple[str, ...] = ()
    paths: Tuple[str, ...] = ()
    purge: str = REPORT
    derived: bool = False
    covered_by: str = ""
    ignored: Tuple[str, ...] = ()
    secret: Tuple[str, ...] = ()
    absent_ok: bool = False
    note: str = ""


@dataclass(frozen=True)
class Exclusion:

    store: str
    table: str
    kind: str
    reason: str
    absent_ok: bool = False
    ignored: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ExcludedStore:

    store: str
    kind: str
    reason: str


class ClaimBook:

    def __init__(self, claims: Iterable[Claim], exclusions: Iterable[Exclusion], stores: Iterable[ExcludedStore] = ()) -> None:
        self.claims: Tuple[Claim, ...] = tuple(claims)
        self.exclusions: Tuple[Exclusion, ...] = tuple(exclusions)
        self.stores: Tuple[ExcludedStore, ...] = tuple(stores)

    def claims_for(self, store: str, table: str) -> List[Claim]:
        return [c for c in self.claims if c.store == store and c.table == table]

    def exclusion_for(self, store: str, table: str) -> Optional[Exclusion]:
        return next((e for e in self.exclusions if e.store == store and e.table == table), None)

    def where_of(self, scope: Scope, store: str, table: str) -> Where:
        for claim in self.claims_for(store, table):
            if scope.kind in claim.scopes and claim.where is not None:
                return claim.where(scope, self)
        return None


def _marks(count: int) -> str:
    return "(" + ", ".join("?" for _ in range(count)) + ")"


def col_in(column: str, key: str) -> WhereFn:
    def build(scope: Scope, _book: ClaimBook) -> Where:
        values = scope.values(key)
        return (f"{column} IN {_marks(len(values))}", values) if values else None
    return build


def json_field_in(column: str, field: str, key: str) -> WhereFn:
    def build(scope: Scope, _book: ClaimBook) -> Where:
        values = scope.values(key)
        if not values:
            return None
        return (f"(CASE WHEN json_valid({column}) THEN json_extract({column}, '$.{field}') END IN {_marks(len(values))})", values)
    return build


def json_target_in(column: str, fields: Tuple[str, ...], key: str) -> WhereFn:
    def build(scope: Scope, _book: ClaimBook) -> Where:
        values = scope.values(key)
        if not values:
            return None
        marks = _marks(len(values))
        terms, params = [], []
        for field in fields:
            terms.append(f"json_extract({column}, '$.{field}') IN {marks}")
            terms.append(f"EXISTS (SELECT 1 FROM json_each({column}, '$.steps') WHERE json_extract(value, '$.{field}') IN {marks})")
            params += [*values, *values]
        return f"(CASE WHEN json_valid({column}) THEN ({' OR '.join(terms)}) END)", params
    return build


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_any(column: str, key: str, template: str) -> WhereFn:
    def build(scope: Scope, _book: ClaimBook) -> Where:
        values = scope.values(key)
        if not values:
            return None
        clause = " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for _ in values)
        return f"({clause})", [template.format(escape_like(str(v))) for v in values]
    return build


def _join(terms: Iterable[WhereFn], scope: Scope, book: ClaimBook, glue: str) -> Where:
    parts = [t(scope, book) for t in terms]
    present = [p for p in parts if p is not None]
    if not present or (glue == "AND" and len(present) != len(parts)):
        return None
    return "(" + f" {glue} ".join(p[0] for p in present) + ")", [v for p in present for v in p[1]]


def any_of(*terms: WhereFn) -> WhereFn:
    return lambda scope, book: _join(terms, scope, book, "OR")


def all_of(*terms: WhereFn) -> WhereFn:
    return lambda scope, book: _join(terms, scope, book, "AND")


def literal(sql: str) -> WhereFn:
    return lambda _scope, _book: (f"({sql})", [])


def via(store: str, parent_table: str, column: str, parent_column: str) -> WhereFn:
    def build(scope: Scope, book: ClaimBook) -> Where:
        parent = book.where_of(scope, store, parent_table)
        if parent is None:
            return None
        return f"{column} IN (SELECT {parent_column} FROM {parent_table} WHERE {parent[0]})", parent[1]
    return build


def scopes_both() -> Tuple[str, str]:
    return (SCOPE_SESSION, SCOPE_PROJECT)
