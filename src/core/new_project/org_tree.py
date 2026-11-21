
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from src.core.project_directory import canonical_path, projects_root
from src.core.session_project_binding import fold_path

ORG_DIR_NAME = "Org"
SKIP_NAMES = frozenset({"node_modules", "__pycache__", "venv", ".git"})
DEFAULT_DEPTH = 4
MAX_DEPTH = 8
MAX_NODES = 2000


def org_root(settings: Any = None) -> str:
    base = projects_root(settings)
    candidate = os.path.join(base, ORG_DIR_NAME)
    return canonical_path(candidate) if os.path.isdir(candidate) else base


def _folded_company_folders(companies: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for company in companies:
        if company.get("folder"):
            out.setdefault(fold_path(company["folder"]), company)
    return out


def _children(path: str) -> List[Tuple[str, str]]:
    try:
        with os.scandir(path) as entries:
            found = [(e.name, e.path) for e in entries
                     if not e.name.startswith(".") and e.name not in SKIP_NAMES and e.is_dir(follow_symlinks=False)]
    except OSError:
        return []
    return sorted(found, key=lambda item: item[0].casefold())


def build_tree(root: str, project_roots: List[str], companies: List[Dict[str, Any]],
               depth: int = DEFAULT_DEPTH, max_nodes: int = MAX_NODES) -> Dict[str, Any]:
    depth = max(1, min(depth, MAX_DEPTH))
    projects = {fold_path(canonical_path(p)) for p in project_roots}
    by_folder = _folded_company_folders(companies)
    budget = [max_nodes]
    truncated = [False]

    def walk(path: str, level: int) -> List[Dict[str, Any]]:
        nodes: List[Dict[str, Any]] = []
        for name, full in _children(path):
            if budget[0] <= 0:
                truncated[0] = True
                break
            budget[0] -= 1
            folded = fold_path(full)
            owner = by_folder.get(folded)
            nodes.append({
                "name": name, "path": full, "project": folded in projects,
                "company": {"id": owner["id"], "name": owner["name"]} if owner else None,
                "children": walk(full, level + 1) if level < depth else [],
            })
        return nodes

    return {"root": root, "nodes": walk(root, 1), "truncated": truncated[0]}


def inside_root(path: str, root: str) -> bool:
    a, b = fold_path(path), fold_path(root)
    return a == b or a.startswith(b + "/")
