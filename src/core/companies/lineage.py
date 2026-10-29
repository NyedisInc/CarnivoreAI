
from __future__ import annotations

import sqlite3
from typing import Dict, Optional

MAX_DEPTH = 4


class CompanyLineageRefused(Exception):
    pass


class CompanyParentCycle(CompanyLineageRefused):
    pass


class CompanyTooDeep(CompanyLineageRefused):
    pass


def parent_map(conn: sqlite3.Connection) -> Dict[int, Optional[int]]:
    columns = {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
    if "parent_id" not in columns:
        return {r[0]: None for r in conn.execute("SELECT id FROM companies")}
    return {r[0]: r[1] for r in conn.execute("SELECT id, parent_id FROM companies")}


def level_of(parents: Dict[int, Optional[int]], company_id: int) -> int:
    level, seen, current = 1, {company_id}, parents.get(company_id)
    while current is not None and current not in seen:
        seen.add(current)
        level += 1
        current = parents.get(current)
    return level


def subtree_height(parents: Dict[int, Optional[int]], company_id: int) -> int:
    children: Dict[int, list] = {}
    for child, parent in parents.items():
        if parent is not None:
            children.setdefault(parent, []).append(child)
    height, frontier, seen = 0, [company_id], set()
    while frontier:
        height += 1
        seen.update(frontier)
        frontier = [c for node in frontier for c in children.get(node, []) if c not in seen]
    return height


def validate_parent(parents: Dict[int, Optional[int]], company_id: Optional[int], parent_id: int) -> None:
    if company_id is not None:
        current: Optional[int] = parent_id
        seen = set()
        while current is not None and current not in seen:
            if current == company_id:
                raise CompanyParentCycle(
                    f"company {parent_id} is company {company_id} or sits under it, so it cannot be its parent"
                )
            seen.add(current)
            current = parents.get(current)
    height = 1 if company_id is None else subtree_height(parents, company_id)
    if level_of(parents, parent_id) + height > MAX_DEPTH:
        raise CompanyTooDeep(f"companies nest at most {MAX_DEPTH} levels deep; this would make it deeper")
