
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, Set

ROOT = Path(__file__).resolve().parents[5]
START = ("src.cplugs.reviewboard.public.edge", "src.cplugs.reviewboard.public.headers", "src.cplugs.reviewboard.public.routes", "src.cplugs.reviewboard.public.listener")
PUBLIC = "src.cplugs.reviewboard.public"
FORBIDDEN = ("src.api", "src.main", "src.core", "src.utils", "src.models", "src.config", "src.cplugs.huddle", "src.cplugs.reviewboard", "src.cplugs.share")
NOT_FOLLOWED = {"src", "src.cplugs", "src.cplugs.sdk", "src.cplugs.reviewboard.public"}
EXPECTED = {"src.cplugs.reviewboard.public.edge", "src.cplugs.reviewboard.public.headers", "src.cplugs.reviewboard.public.routes", "src.cplugs.reviewboard.public.listener",
            "src.cplugs.sdk.sandboxed_html", "src.cplugs.reviewboard.public.read", "src.cplugs.reviewboard.public.resolve", "src.cplugs.reviewboard.public.respond",
            "src.cplugs.reviewboard.public.assets", "src.cplugs.reviewboard.public.capability", "src.cplugs.reviewboard.public.ratelimit", "src.cplugs.reviewboard.public.deps", "src.cplugs.reviewboard.public.health",
            "src.cplugs.reviewboard.public.write", "src.cplugs.reviewboard.public.submission", "src.cplugs.sdk.visible_text", "src.cplugs.reviewboard.public.waiting",
            "src.cplugs.reviewboard.public.singleflight", "src.cplugs.reviewboard.public.theme", "src.cplugs.reviewboard.public.presence"}


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
    assert [m for m in reachable(("src.cplugs.sdk.routing",)) if forbidden(m)], "routing.py imports the API; the walk must say so"


def package_level_imports(source: str) -> list:
    return [n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom) and not n.level and n.module in NOT_FOLLOWED]


def test_the_request_path_never_imports_from_a_package_init() -> None:
    found = {m: package_level_imports(module_file(m).read_text()) for m in sorted(EXPECTED)}
    assert {m: v for m, v in found.items() if v} == {}


def test_the_boundary_can_fail_inside_the_plugin() -> None:
    assert forbidden("src.cplugs.reviewboard.service") and forbidden("src.cplugs.reviewboard.public_port") and forbidden("src.cplugs.reviewboard")
    assert not forbidden("src.cplugs.reviewboard.public.edge") and not forbidden("src.cplugs.reviewboard.public")


def test_the_package_level_check_can_fail() -> None:
    assert package_level_imports("from src.cplugs.sdk import SettingsVerdict\n") == ["src.cplugs.sdk"]
    assert package_level_imports("from src.cplugs.reviewboard.public.listener import MAX_HEAD_BYTES\n") == []
