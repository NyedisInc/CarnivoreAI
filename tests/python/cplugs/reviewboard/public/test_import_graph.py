
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, Set

ROOT = Path(__file__).resolve().parents[5]
START = ("src.plugins.reviewboard.public.edge", "src.plugins.reviewboard.public.headers", "src.plugins.reviewboard.public.routes", "src.plugins.reviewboard.public.listener")
PUBLIC = "src.plugins.reviewboard.public"
FORBIDDEN = ("src.api", "src.main", "src.core", "src.utils", "src.models", "src.config", "src.plugins.taskmanager", "src.plugins.reviewboard", "src.plugins.share")
NOT_FOLLOWED = {"src", "src.plugins", "src.plugins.sdk", "src.plugins.reviewboard.public"}
EXPECTED = {"src.plugins.reviewboard.public.edge", "src.plugins.reviewboard.public.headers", "src.plugins.reviewboard.public.routes", "src.plugins.reviewboard.public.listener",
            "src.plugins.sdk.sandboxed_html", "src.plugins.reviewboard.public.read", "src.plugins.reviewboard.public.resolve", "src.plugins.reviewboard.public.respond",
            "src.plugins.reviewboard.public.assets", "src.plugins.reviewboard.public.capability", "src.plugins.reviewboard.public.ratelimit", "src.plugins.reviewboard.public.deps", "src.plugins.reviewboard.public.health",
            "src.plugins.reviewboard.public.write", "src.plugins.reviewboard.public.submission", "src.plugins.sdk.visible_text", "src.plugins.reviewboard.public.waiting",
            "src.plugins.reviewboard.public.singleflight", "src.plugins.reviewboard.public.theme", "src.plugins.reviewboard.public.presence"}


def forbidden(module: str) -> bool:
    inside = module == PUBLIC or module.startswith(PUBLIC + ".")
    return module.startswith(FORBIDDEN) and not inside


def module_file(name: str) -> Path:
    base = ROOT / Path(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(name)


def imports_of(path: Path) -> Iterator[str]:
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names if a.name.startswith("src"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src") and not node.level:
            yield node.module
            for alias in node.names:
                try:
                    module_file(f"{node.module}.{alias.name}")
                except FileNotFoundError:
                    continue
                yield f"{node.module}.{alias.name}"


def reachable(start: tuple = START) -> Set[str]:
    seen: Set[str] = set()
    todo = list(start)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in NOT_FOLLOWED:
            continue
        try:
            todo += list(imports_of(module_file(name)))
        except FileNotFoundError:
            continue
    return seen


def test_the_public_request_path_reaches_nothing_of_the_main_app() -> None:
    reached = reachable()
    assert not [m for m in reached if forbidden(m)], sorted(m for m in reached if forbidden(m))
    assert reached - NOT_FOLLOWED == EXPECTED, sorted(reached - NOT_FOLLOWED ^ EXPECTED)


def test_the_walk_can_fail() -> None:
    assert [m for m in reachable(("src.plugins.sdk.routing",)) if forbidden(m)], "routing.py imports the API; the walk must say so"


def package_level_imports(source: str) -> list:
    return [n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom) and not n.level and n.module in NOT_FOLLOWED]


def test_the_request_path_never_imports_from_a_package_init() -> None:
    found = {m: package_level_imports(module_file(m).read_text()) for m in sorted(EXPECTED)}
    assert {m: v for m, v in found.items() if v} == {}


def test_the_boundary_can_fail_inside_the_plugin() -> None:
    assert forbidden("src.plugins.reviewboard.service") and forbidden("src.plugins.reviewboard.public_port") and forbidden("src.plugins.reviewboard")
    assert not forbidden("src.plugins.reviewboard.public.edge") and not forbidden("src.plugins.reviewboard.public")


def test_the_package_level_check_can_fail() -> None:
    assert package_level_imports("from src.plugins.sdk import SettingsVerdict\n") == ["src.plugins.sdk"]
    assert package_level_imports("from src.plugins.reviewboard.public.listener import MAX_HEAD_BYTES\n") == []
