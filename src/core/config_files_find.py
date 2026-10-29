from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import structlog

from src.core import config_files
from src.core.config_files_constants import BLOCKLIST_ONLY_ROOTS

logger = structlog.get_logger()

FIND_LIMIT = 500

FIND_MAX_DEPTH = 12

FIND_BUDGET_S = 4.0

MAX_QUERY_LEN = 200


def _leaf(root: Path, path: Path, depth: int, root_id: str) -> Optional[dict]:
    node = config_files._build_node(root, path, depth, depth, root_id)
    return config_files._node_to_dict(node) if node is not None else None


def find(
    root_id: str,
    rel_path: str,
    project_path: Optional[str],
    query: str,
    limit: int = FIND_LIMIT,
) -> tuple[list, bool]:
    needle = (query or "").strip().lower()
    if not needle or len(needle) > MAX_QUERY_LEN:
        raise config_files.ConfigFileError("query must be 1 to 200 characters")
    roots = config_files.resolve_roots(project_path)
    root = roots.get(root_id)
    if root is None:
        raise config_files.ConfigFileError(f"unknown or unavailable root: {root_id}")
    start = config_files.resolve_safe_path(root_id, rel_path, project_path)
    if not start.is_dir():
        raise config_files.ConfigFileError("not a directory")
    requested = (rel_path or "").strip().strip("/")
    base_depth = 0 if requested in ("", ".") else len(requested.split("/"))

    deadline = time.monotonic() + FIND_BUDGET_S
    matches: list[tuple[Path, int]] = []
    truncated = False
    stack: list[tuple[Path, int]] = [(start, base_depth)]
    while stack:
        directory, depth = stack.pop()
        if time.monotonic() > deadline:
            truncated = True
            break
        try:
            with os.scandir(directory) as it:
                entries = list(it)
        except OSError as exc:
            logger.info("config_files_find_listdir_failed", path=str(directory), error=str(exc))
            continue
        for entry in entries:
            if config_files._is_hidden(entry.name, root_id):
                continue
            path = Path(entry.path)
            if depth == 0 and root_id not in BLOCKLIST_ONLY_ROOTS and _leaf(root, path, 0, root_id) is None:
                continue
            if needle in entry.name.lower():
                matches.append((path, depth))
                if len(matches) >= limit:
                    truncated = True
                    stack.clear()
                    break
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir and depth < FIND_MAX_DEPTH:
                stack.append((path, depth + 1))
            elif is_dir:
                truncated = True
    if truncated:
        logger.info("config_files_find_truncated", root=root_id, matches=len(matches))
    return _prune(root, root_id, start, base_depth, matches), truncated


def _prune(root: Path, root_id: str, start: Path, base_depth: int, matches: list) -> list:
    nodes: dict[Path, dict] = {}
    top: list[dict] = []

    def ensure(path: Path, depth: int) -> Optional[dict]:
        if path in nodes:
            return nodes[path]
        node = _leaf(root, path, depth, root_id)
        if node is None:
            return None
        if node["is_dir"]:
            node["children_loaded"] = False
        nodes[path] = node
        parent = path.parent
        if parent == start:
            top.append(node)
        else:
            parent_node = ensure(parent, depth - 1)
            if parent_node is None:
                return None
            parent_node["children"].append(node)
        return node

    for path, depth in matches:
        ensure(path, depth)

    def order(items: list) -> None:
        items.sort(key=lambda n: (not n["is_dir"], n["name"].lower()))
        for n in items:
            if n["children"]:
                order(n["children"])

    order(top)
    return top
