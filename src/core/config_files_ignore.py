from __future__ import annotations

import os
import subprocess
from src.core.dev_tools import git_guard
from pathlib import Path
from typing import Iterator, Literal

import structlog

logger = structlog.get_logger()

IgnoreStatus = Literal["ok", "unavailable"]

MAX_PATHS = 50_000

TIMEOUT_S = 5.0


def _walk(nodes: list) -> Iterator[dict]:
    for node in nodes:
        if node.get("kind") == "more" or node.get("name") == ".git":
            continue
        yield node
        children = node.get("children") or []
        if children:
            yield from _walk(children)


def _query_path(node: dict, is_link: bool) -> str:
    rel = "./" + node["rel_path"]
    return rel + "/" if node.get("is_dir") and not is_link else rel


def _beyond_a_link(root_dir: Path, rel_path: str, cache: dict) -> bool:
    parts = rel_path.split("/")
    for i in range(1, len(parts)):
        prefix = "/".join(parts[:i])
        if prefix not in cache:
            cache[prefix] = (root_dir / prefix).is_symlink()
        if cache[prefix]:
            return True
    return False


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def ignored_paths(root_dir: Path, paths: list[str]) -> set[str] | None:
    """
    Description: ask git which of ``paths`` (relative to ``root_dir``) it
      ignores.
    Inputs: root_dir (Path) - the resolved root directory; paths (list[str])
      - relative paths, each starting with ``./``, directories with a
      trailing slash.
    Output: set[str] of the ignored inputs, exactly as given; or None when
      git could not answer (not a repository, git missing, timeout, bound).
    Example: ignored_paths(Path("/repo"), ["./dist/", "./src/"]) -> {"./dist/"}
    """
    if len(paths) > MAX_PATHS:
        logger.info("config_files_ignore_bound", count=len(paths), bound=MAX_PATHS)
        return None
    if not paths:
        return set()
    if not git_guard.git_available():
        logger.info("config_files_ignore_no_git")
        return None
    payload = "\0".join(paths).encode("utf-8") + b"\0"
    try:
        proc = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "check-ignore", "-z", "--stdin"],
            cwd=str(root_dir),
            input=payload,
            capture_output=True,
            timeout=TIMEOUT_S,
            env=_git_env(),
            check=False,
        )
    except FileNotFoundError:
        logger.info("config_files_ignore_no_git")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("config_files_ignore_timeout", timeout_s=TIMEOUT_S, count=len(paths))
        return None
    except OSError as exc:
        logger.warning("config_files_ignore_failed", error=str(exc))
        return None
    if proc.returncode not in (0, 1):
        return None
    out = proc.stdout.decode("utf-8", errors="replace")
    return {p for p in out.split("\0") if p}


def mark_ignored(root_dir: Path, nodes: list) -> IgnoreStatus:
    """
    Description: set ``is_ignored`` on every node of a listing, in place,
      from one git query.
    Inputs: root_dir (Path) - the resolved root the listing's rel_paths are
      relative to; nodes (list[dict]) - ``list_subtree`` output.
    Output: "ok" when git answered (every node now carries ``is_ignored``);
      "unavailable" when it could not (no node is changed).
    Example: mark_ignored(Path("/repo"), tree) -> "ok"
    """
    flat = list(_walk(nodes))
    cache: dict[str, bool] = {}
    queries: list[tuple[dict, str | None]] = []
    for node in flat:
        rel = node["rel_path"]
        if _beyond_a_link(root_dir, rel, cache):
            queries.append((node, None))
        else:
            queries.append((node, _query_path(node, (root_dir / rel).is_symlink())))
    answer = ignored_paths(root_dir, [q for _, q in queries if q is not None])
    if answer is None:
        return "unavailable"
    for node, query in queries:
        node["is_ignored"] = query is not None and query in answer
    return "ok"
