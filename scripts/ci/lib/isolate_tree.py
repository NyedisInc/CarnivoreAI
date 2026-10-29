#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

EXIT_COULD_NOT_ISOLATE = 2


def load_tree_copy(repo: Path) -> ModuleType:
    path = repo / "scripts" / "gate" / "tree_copy.py"
    spec = importlib.util.spec_from_file_location("mutate_tree_copy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolate(dest: Path, repo: Path) -> None:
    tree_copy = load_tree_copy(repo)
    tree_copy.copy_tree(dest, repo)
    tree_copy.link_venv(dest, repo)
    modules = repo / "web" / "node_modules"
    if modules.exists() and (dest / "web").is_dir():
        (dest / "web" / "node_modules").symlink_to(modules.resolve())


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: isolate_tree.py <dest> <repo>", file=sys.stderr)
        return EXIT_COULD_NOT_ISOLATE
    try:
        isolate(Path(argv[1]), Path(argv[2]))
    except (ImportError, OSError, RuntimeError) as exc:
        print(f"isolate_tree: {exc}", file=sys.stderr)
        return EXIT_COULD_NOT_ISOLATE
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
