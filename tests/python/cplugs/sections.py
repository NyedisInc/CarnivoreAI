
from __future__ import annotations

import ast
from pathlib import Path
from typing import FrozenSet, Iterator, List, Tuple

ROOT = Path(__file__).resolve().parents[3]
CPLUGS = ROOT / "src" / "cplugs"
CPLUGS_PACKAGE = "src.cplugs"
PLATFORM_DIRS: Tuple[str, ...] = ("host", "runtime", "sdk", "sdk_py")
SDK_PACKAGE = "src.cplugs.sdk"
CORE_PREFIX = "src."
ROW_ARROW = " -> "


def source_dirs() -> List[str]:
    return sorted(p.name for p in CPLUGS.iterdir() if p.is_dir() and not p.name.startswith("__") and any(p.rglob("*.py")))


def known_modules(rows: Tuple[str, ...], feature_id: str) -> FrozenSet[str]:
    pairs = (row.split(ROW_ARROW, 1) for row in rows)
    return frozenset(module for feature, module in pairs if feature == feature_id)


def feature_ids() -> List[str]:
    return sorted(p.name for p in CPLUGS.iterdir() if p.is_dir() and p.name not in PLATFORM_DIRS and (p / "__init__.py").exists())


def platform_files() -> List[Path]:
    files = [path for name in PLATFORM_DIRS for path in (CPLUGS / name).rglob("*.py")]
    return sorted(files + list(CPLUGS.glob("*.py")))


def imported_modules(source: str, known: FrozenSet[str] = frozenset()) -> Iterator[str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            declared = [f"{module}.{alias.name}" for alias in node.names]
            if known and all(name in known for name in declared):
                yield from declared
                continue
            yield module
            if module == CPLUGS_PACKAGE:
                yield from declared


def feature_of(module: str, features: List[str]) -> str:
    parts = module.split(".")
    if len(parts) >= 3 and ".".join(parts[:2]) == CPLUGS_PACKAGE and parts[2] in features:
        return parts[2]
    return ""


def platform_violations(source: str, features: List[str]) -> List[str]:
    return [module for module in imported_modules(source) if feature_of(module, features)]


def core_imports(source: str, known: FrozenSet[str] = frozenset()) -> List[str]:
    return [m for m in imported_modules(source, known) if m.startswith(CORE_PREFIX) and not m.startswith(f"{CPLUGS_PACKAGE}.") and m != CPLUGS_PACKAGE]
