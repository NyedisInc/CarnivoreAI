
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHART = REPO_ROOT / "docs" / "session-project-operations.md"

def _router_files() -> Tuple[str, ...]:
    found = []
    for path in sorted((REPO_ROOT / "src" / "api").glob("*.py")):
        if path.name == "__init__.py":
            continue
        if "= APIRouter(" not in path.read_text():
            continue
        found.append(str(path.relative_to(REPO_ROOT)))
    assert len(found) >= 25, found
    return tuple(found)


ROUTER_FILES: Tuple[str, ...] = _router_files()

_SYMBOL_CITATION = re.compile(
    r"(?<![\w/.])((?:src|client|tests|macOS|web)/[\w./-]+\.(?:py|js|ts|svelte))"
    r"::([A-Za-z_]\w*)"
)

_MODULE_CITATION = re.compile(
    r"(?<![\w/.])((?:src|client|tests|macOS|web)/[\w./-]+\.(?:py|js|ts|svelte))"
    r"(?!::)(?![\w/.])"
)

_ROUTE_CITATION = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./{}-]*)"
)

_ROUTE_DECORATOR = re.compile(
    r"@(?:router|page_router)\.(get|post|put|patch|delete)\(\s*\"([^\"]*)\"",
    re.MULTILINE,
)

_ROUTER_PREFIXES: Dict[str, Tuple[str, ...]] = {
    "src/api/session_groups_routes.py": ("/session-groups",),
    "src/api/config_files_routes.py": ("/config-files",),
    "src/api/autonomy_routes.py": ("/autonomy",),
}


def _read_chart() -> str:
    if not CHART.exists():
        pytest.fail(
            f"CANNOT DETERMINE: {CHART} does not exist, so no citation was "
            "checked. This is not a passing run."
        )
    text = CHART.read_text(encoding="utf-8")
    if not text.strip():
        pytest.fail(f"CANNOT DETERMINE: {CHART} is empty.")
    return text


def _python_symbols(path: Path) -> Set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


_JS_DEFINITION = re.compile(
    r"(?:function\s+(\w+)"
    r"|(?:async\s+)?(\w+)\s*\("
    r"|(?:const|let|var)\s+(\w+)\s*=)"
)


def _js_symbols(path: Path) -> Set[str]:
    text = path.read_text(encoding="utf-8")
    return {m for groups in _JS_DEFINITION.findall(text) for m in groups if m}


def _normalise_route(raw: str) -> str:
    trimmed = raw.rstrip("/") or "/"
    parts = []
    for seg in trimmed.split("/"):
        if seg.startswith("{") or seg in _PARAM_WORDS:
            parts.append("*")
        else:
            parts.append(seg)
    return "/".join(parts)


_PARAM_WORDS: Set[str] = {
    "session_id",
    "session_uuid",
    "session_name",
    "project_name",
    "group_uuid",
    "name",
    "wrapper_id",
    "toast_id",
}


def _declared_routes() -> Set[Tuple[str, str]]:
    found: Set[Tuple[str, str]] = set()
    for rel in ROUTER_FILES:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        prefixes = _ROUTER_PREFIXES.get(rel, ("",))
        for method, route in _ROUTE_DECORATOR.findall(text):
            for prefix in prefixes:
                found.add(
                    (method.upper(), _normalise_route(f"{prefix}{route}"))
                )
    return found




def test_chart_is_readable_and_actually_cites_things():
    text = _read_chart()
    symbols = _SYMBOL_CITATION.findall(text)
    routes = _ROUTE_CITATION.findall(text)
    assert len(symbols) >= 40, (
        "the citation extractor found "
        f"{len(symbols)} path::symbol citations, which is far fewer than the "
        "chart carries. The extractor is broken, not the chart - a low count "
        "here would make every other assertion in this file vacuous."
    )
    assert len(routes) >= 10, (
        f"only {len(routes)} METHOD /route citations found; the extractor is "
        "not matching the document."
    )


def test_every_cited_file_exists():
    text = _read_chart()
    cited = {m for m, _ in _SYMBOL_CITATION.findall(text)}
    cited |= set(_MODULE_CITATION.findall(text))
    missing = sorted(p for p in cited if not (REPO_ROOT / p).exists())
    assert not missing, (
        "docs/session-project-operations.md cites files that no longer "
        f"exist: {missing}"
    )


def test_every_cited_symbol_is_defined_in_the_file_it_is_cited_from():
    text = _read_chart()
    by_file: Dict[str, Set[str]] = {}
    for rel, symbol in _SYMBOL_CITATION.findall(text):
        by_file.setdefault(rel, set()).add(symbol)

    broken: List[str] = []
    for rel, wanted in sorted(by_file.items()):
        path = REPO_ROOT / rel
        if not path.exists():
            broken.append(f"{rel} (file missing)")
            continue
        defined = _python_symbols(path) if rel.endswith(".py") else _js_symbols(path)
        for symbol in sorted(wanted):
            if symbol not in defined:
                broken.append(f"{rel}::{symbol}")

    assert not broken, (
        "docs/session-project-operations.md names symbols that are not "
        "defined where it says they are. Either the code moved and the chart "
        "is now fiction, or the citation is a typo:\n  "
        + "\n  ".join(broken)
    )


def test_every_cited_route_is_declared_by_a_router():
    text = _read_chart()
    declared = _declared_routes()
    assert declared, (
        "CANNOT DETERMINE: no route decorators were parsed out of any router "
        "file, so no route citation was really checked."
    )

    broken: List[str] = []
    for method, route in _ROUTE_CITATION.findall(text):
        key = (method.upper(), _normalise_route(route))
        if key not in declared:
            broken.append(f"{method} {route}")

    assert not broken, (
        "docs/session-project-operations.md names routes that no router "
        f"declares: {sorted(set(broken))}"
    )


def test_the_gui_fork_the_chart_now_claims_actually_exists():
    declared = _declared_routes()
    fork_routes = sorted(r for _, r in declared if "fork" in r.lower())
    assert fork_routes, (
        "docs/session-project-operations.md section 4 says the GUI fork "
        "ships, but no router declares a fork route."
    )

    client = REPO_ROOT / "client" / "js"
    callers: List[str] = []
    if client.is_dir():
        for js in sorted(client.glob("*.js")):
            body = js.read_text(encoding="utf-8", errors="replace")
            if re.search(r"\bforkSession\b", body):
                callers.append(str(js.relative_to(REPO_ROOT)))
    assert callers, (
        "section 4 says the fork is reachable from the interface, but no "
        "client file calls forkSession."
    )

    chart = (REPO_ROOT / "docs" / "session-project-operations.md").read_text(
        encoding="utf-8"
    )
    assert "fork - CLI | **NOT IMPLEMENTED**" in chart, (
        "the CLI fork is still unbuilt and is the INVERSE shape of the GUI "
        "fork; the chart must keep saying so."
    )
