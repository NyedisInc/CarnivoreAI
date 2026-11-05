"""The MCP route coverage ratchet (#1470; CLAUDE.md: every user-facing action goes through a documented, authenticated route, and the app is MCP-controllable, #152).

Every authenticated route of the real app has exactly one decision: a tool calls its route function (found by reading the
tool modules' source), or ``route_coverage_ledger.json`` has a row for it:

- ``tool:<name>``: an existing, SWITCHED-ON tool covers it through a service rather than the route function.
- ``retired:<name>``: a tool exists but is switched off by default (``deprecated_tools.DEPRECATED``, which ``tool_switches.DEFAULT_OFF`` mirrors; read here because the suite's conftest
  replaces ``DEFAULT_OFF``), so an agent cannot use it
  unless the owner turns it on. Not coverage; listed apart so the debt stays visible.
- ``out:<reason>``: it gets no tool, on purpose (``REASONS``).
- ``deferred:<slice>``: a tool is still to be built (the slice plan is ``docs/mcp-server.md``, "Route coverage ledger").

RED WHEN: a new route has no decision, a ledger row names a route that is gone, a ledger row is for a route a tool now
covers (build the tool, delete the row: this is how the deferred list shrinks), a ``tool:`` row names a tool that is not
registered or is switched off (or a ``retired:`` row names one that is on), a reason or slice is malformed, or the deferred
count is not exactly :data:`DEFERRED_RATCHET`. The ratchet only goes down. Raising it needs the other operator's written yes in
the commit: a convention in the spirit of the top-down gate rule (CLAUDE.md), reviewed by a person, not enforced by a script.
"""

from __future__ import annotations

import ast
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_cov_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_cov_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi.routing import APIRoute  # noqa: E402

from src.api.auth import require_auth  # noqa: E402
from src.core.mcp import deprecated_tools, tools  # noqa: E402
from src.main import app  # noqa: E402
from tests.test_route_auth_inventory import _dep_calls, _walk  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
LEDGER = Path(__file__).with_name("route_coverage_ledger.json")
MCP_SOURCE = ROOT / "src" / "core" / "mcp"
REASONS = frozenset({
    "credentials",
    "approval-model",
    "owner-only",
    "platform",
    "huddle",
    "plugin-owned",
    "plumbing",
    "ui-asset",
    "superseded",
})
DEFERRED_RATCHET = 216
_ROUTE_REF = re.compile(r"(src\.[a-z_.]+):([A-Za-z_0-9]+)")
_ROW = re.compile(r"^(tool|retired|out|deferred):(.+)$")


def guarded_routes() -> Dict[str, Tuple[str, str]]:
    """Every authenticated HTTP route of the real app. Output: {"METHOD /full/path": (endpoint module, endpoint function)}."""
    found: Dict[str, Tuple[str, str]] = {}
    for path, route, inherited in ((p, r, i) for kind, p, r, i in _walk(app.routes) if kind == "http"):
        if not isinstance(route, APIRoute):
            continue
        calls = set(_dep_calls(route.dependant)) | set(inherited)
        if require_auth in calls or any(hasattr(c, "peer_scope") for c in calls):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found[f"{method} {path}"] = (route.endpoint.__module__, route.endpoint.__name__)
    return found


def _docstring_nodes(tree: ast.AST) -> Set[int]:
    """The ids of every docstring ``Constant`` node in ``tree``, so quoted examples in prose are not read as routes. Output: set of ids."""
    ids: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node, clean=False):
            ids.add(id(node.body[0].value))  # type: ignore[attr-defined]
    return ids


def live_nodes(tree: ast.Module, switched_off: Iterable[str] = ()) -> List[ast.AST]:
    """Every node of ``tree`` except the bodies of top-level functions named like a switched-off tool.

    Why: a route imported only by a deprecated tool's handler is not reachable by an agent, so it is not coverage. A
    module-level ``RouteTool`` spec cannot be attributed to a tool this way and always counts. Output: list of nodes.
    """
    off = set(switched_off)
    keep = [n for n in tree.body if not (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in off)]
    return [node for top in keep for node in ast.walk(top)]


def route_strings(text: str, switched_off: Iterable[str] = ()) -> Set[Tuple[str, str]]:
    """The (module, function) pairs named by ``"src.x.y:func"`` string literals in code, docstrings and comments excluded.

    Inputs: text (Python source); switched_off (tool names whose top-level handler is skipped). Output: set of (dotted module, function name).
    Example: route_strings('X = "src.api.a:f"') -> {("src.api.a", "f")}
    """
    tree = ast.parse(text)
    skip = _docstring_nodes(tree)
    found: Set[Tuple[str, str]] = set()
    for node in live_nodes(tree, switched_off):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            match = _ROUTE_REF.fullmatch(node.value)
            if match:
                found.add((match.group(1), match.group(2)))
    return found


def called_route_functions(source_dir: Path = MCP_SOURCE, switched_off: Iterable[str] = deprecated_tools.DEPRECATED) -> Set[Tuple[str, str]]:
    """The (module, function) pairs the SWITCHED-ON MCP tool code calls: a ``RouteTool`` route string, or a function imported from ``src.api`` / ``src.cplugs``.

    Why source and not runtime: a tool imports its route lazily inside its handler, so only the text says which route it reaches.
    Output: set of (dotted module, function name).
    """
    called: Set[Tuple[str, str]] = set()
    for path in source_dir.rglob("*.py"):
        text = path.read_text()
        called.update(route_strings(text, switched_off))
        for node in live_nodes(ast.parse(text), switched_off):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(("src.api", "src.cplugs")):
                called.update((node.module, alias.name) for alias in node.names)
    return called


def ledger_rows() -> Dict[str, str]:
    """The ledger's rows. Output: {"METHOD /path": "status:detail"}."""
    return json.loads(LEDGER.read_text())["routes"]


def ledger_problems(routes: Dict[str, Tuple[str, str]], called: Set[Tuple[str, str]], rows: Dict[str, str],
                    registered: Iterable[str], switched_off: Iterable[str] = ()) -> List[str]:
    """Every way the ledger disagrees with the app and the tools. Output: list of one-line problems, empty when it holds.

    Inputs: routes (guarded_routes()); called (called_route_functions()); rows (ledger_rows()); registered (tool names);
      switched_off (tool names off by default).
    Example: ledger_problems({"GET /a": ("m", "f")}, set(), {}, []) -> ["GET /a: no tool and no ledger row ..."]
    """
    names, off = set(registered), set(switched_off)
    out: List[str] = []
    for key, endpoint in sorted(routes.items()):
        covered = endpoint in called
        row = rows.get(key)
        if row is None and not covered:
            out.append(f"{key}: no tool and no ledger row; build the tool or add a row (out:<reason> / deferred:<slice>)")
        elif row is not None and covered:
            out.append(f"{key}: a tool now calls this route; delete its ledger row ({row})")
    for key, row in sorted(rows.items()):
        match = _ROW.match(row)
        if key not in routes:
            out.append(f"{key}: ledger row for a route that is gone or no longer authenticated")
        elif match is None:
            out.append(f"{key}: malformed row {row!r}")
        elif match.group(1) in ("tool", "retired") and match.group(2) not in names:
            out.append(f"{key}: names tool {match.group(2)!r}, which is not registered")
        elif match.group(1) == "tool" and match.group(2) in off:
            out.append(f"{key}: tool {match.group(2)!r} is switched off by default; the row must be retired:{match.group(2)}")
        elif match.group(1) == "retired" and match.group(2) not in off:
            out.append(f"{key}: tool {match.group(2)!r} is switched on; the row must be tool:{match.group(2)}")
        elif match.group(1) == "out" and match.group(2) not in REASONS:
            out.append(f"{key}: unknown reason {match.group(2)!r}")
        elif match.group(1) == "deferred" and not match.group(2).isdigit():
            out.append(f"{key}: deferred needs a slice number, got {match.group(2)!r}")
    return out


def deferred_count(rows: Dict[str, str]) -> int:
    """How many ledger rows are ``deferred``. Output: int."""
    return sum(1 for row in rows.values() if row.startswith("deferred:"))


@pytest.fixture(scope="module")
def world() -> Tuple[Dict[str, Tuple[str, str]], Set[Tuple[str, str]], Dict[str, str]]:
    """The live route table, the called route functions and the ledger, read once. Output: (routes, called, rows)."""
    return guarded_routes(), called_route_functions(), ledger_rows()


def test_every_authenticated_route_has_exactly_one_decision(world) -> None:
    """No route is undecided, stale or covered twice: ledger_problems finds nothing on the real app."""
    routes, called, rows = world
    assert len(routes) > 800 and len(called) > 100
    assert ledger_problems(routes, called, rows, tools.tool_names(), deprecated_tools.DEPRECATED) == []


def test_the_deferred_count_is_the_ratchet(world) -> None:
    """The ledger's deferred rows are exactly DEFERRED_RATCHET, so the number can only fall with the rows."""
    count = deferred_count(world[2])
    assert count == DEFERRED_RATCHET, (
        f"{count} deferred routes, ratchet says {DEFERRED_RATCHET}: lower DEFERRED_RATCHET to match when a slice lands; "
        "raising it is the other operator's call")


def test_the_check_goes_red_on_each_kind_of_drift() -> None:
    """Red control: each way the ledger can lie is reported, so a green run above proves the check looked."""
    routes = {"GET /a": ("m", "a"), "GET /b": ("m", "b"), "GET /c": ("m", "c")}
    called = {("m", "b")}
    rows = {"GET /a": "deferred:2", "GET /gone": "out:huddle"}
    found = ledger_problems(routes, called, {**rows, "GET /b": "deferred:1"}, [])
    assert any(p.startswith("GET /c: no tool") for p in found)
    assert any(p.startswith("GET /b: a tool now calls") for p in found)
    assert any(p.startswith("GET /gone:") for p in found)
    assert ledger_problems(routes, called, {"GET /a": "tool:nope", "GET /c": "out:whim"}, ["x"]) == [
        "GET /a: names tool 'nope', which is not registered", "GET /c: unknown reason 'whim'"]
    assert ledger_problems({"GET /a": ("m", "a")}, set(), {"GET /a": "deferred:x"}, []) == [
        "GET /a: deferred needs a slice number, got 'x'"]
    assert ledger_problems({"GET /a": ("m", "a")}, {("m", "a")}, {}, []) == []
    off = ledger_problems({"GET /a": ("m", "a"), "GET /b": ("m", "b")}, set(), {"GET /a": "tool:old", "GET /b": "retired:new"},
                          ["old", "new"], ["old"])
    assert len(off) == 2 and "must be retired:old" in off[0] and "must be tool:new" in off[1]


def test_a_route_named_in_a_docstring_or_comment_is_not_a_tool_call() -> None:
    """Red control for the scan: only a string literal in code counts, so prose and examples cannot fake coverage."""
    assert route_strings('X = "src.api.a:f"\nY = ["src.api.b:g"]') == {("src.api.a", "f"), ("src.api.b", "g")}
    assert route_strings('"""module note: "src.api.a:f" """\ndef h():\n    """example "src.api.b:g" """\n    # "src.api.c:i"\n') == set()
    assert route_strings('Z = "not a route: src.api.a:f"') == set()
    src = 'def old_tool():\n    from src.api.m import f\n    return "src.api.m:f"\n'
    assert route_strings(src) == {("src.api.m", "f")} and route_strings(src, ["old_tool"]) == set()


def test_every_slice_one_route_is_covered_and_off_the_ledger(world) -> None:
    """Slice 1 (session inspection reads) is built: its routes are called by tools and carry no ledger row."""
    routes, called, rows = world
    built = {"GET /api/v1/sessions/{session_id}/subagents", "GET /api/v1/sessions/{session_id}/git-diff",
             "GET /api/v1/sessions/restore-offer", "GET /api/v1/sessions/{session_uuid}/conversations"}
    assert built <= set(routes) and all(routes[k] in called and k not in rows for k in built)
