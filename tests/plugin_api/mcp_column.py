
from __future__ import annotations

import re
from typing import Callable, Dict, FrozenSet, List, Set

from tests.plugin_api import contract_parse as cp

MCP_NONE = re.compile(r"^none: ([a-z-]+)$")
GET = "GET"
CONSENT_FIELD = "consent"
CONFIRM_FIELD = "confirm_token"
SHEET_SUFFIX = "/sheet"
CATALOG_PREFIX = "/api/v1/catalog/"
OWNER_PREFIX = "/api/v1/cplug-owner/"
SAFE_MODE_PATH = "/api/v1/cplugs/safe-mode"
SECRETS_SEGMENT = "/secrets/"
PLUGIN_FORWARD_MODULE = "src/plugins/host/sidecar_routes.py::"
INSPECTOR_MODULE = "src/plugins/host/inspector_routes.py::"
UI_ASSET_SEGMENTS = ("/ui/", "/preview", "/view/", "/slots", "/icon", "/screenshots/")

EXTRA_REACH: Dict[str, FrozenSet[str]] = {
    "plugin_sideload_add": frozenset({"src.plugins.host.sideload_git_routes:post_sideload_git"}),
    "plugins_list": frozenset({"src.plugins.host.routes:list_cplugs", "src.plugins.host.routes:get_cplug",
                               "src.api.plugin_health_routes:get_health"}),
}


def _verbs(row: Dict[str, str]) -> Set[str]:
    return set(cp.doc_verbs(row["Verb"]))


def _inputs(row: Dict[str, str]) -> Set[str]:
    return set(re.findall(r"[a-z_]+", cp.first_ticked(row["Inputs"])))


REASON_FITS: Dict[str, Callable[[Dict[str, str]], bool]] = {
    "consent": lambda r: CONSENT_FIELD in _inputs(r) or cp.first_ticked(r["Path"]).endswith(SHEET_SUFFIX),
    "owner-switch": lambda r: cp.first_ticked(r["Path"]).startswith(OWNER_PREFIX) or cp.first_ticked(r["Path"]) == SAFE_MODE_PATH,
    "credentials": lambda r: SECRETS_SEGMENT in cp.first_ticked(r["Path"]),
    "owner-only": lambda r: CONFIRM_FIELD in _inputs(r),
    "plugin-owned": lambda r: cp.first_ticked(r["Where"]).startswith(PLUGIN_FORWARD_MODULE),
    "ui-asset": lambda r: any(s in cp.first_ticked(r["Path"]) for s in UI_ASSET_SEGMENTS) and cp.first_ticked(r["Inputs"]) == cp.NONE_CELL,
    "platform": lambda r: cp.first_ticked(r["Path"]).startswith(CATALOG_PREFIX),
    "webhook": lambda r: "/webhook/" in cp.first_ticked(r["Path"]),
    "inspector": lambda r: cp.first_ticked(r["Where"]).startswith(INSPECTOR_MODULE) and cp.first_ticked(r["Path"]).endswith(("/inspector", "/pause", "/resume")),
}


def handler_reference(cite: str) -> str:
    path, _, function = cite.partition("::")
    return f"{path.removesuffix('.py').replace('/', '.')}:{function}"


def tool_reach() -> Dict[str, Set[str]]:
    from src.core.mcp import tools

    reach: Dict[str, Set[str]] = {s.name: {s.route} for m in tools._ROUTE_MODULES for s in getattr(m, "SPECS", ())}
    for name, extra in EXTRA_REACH.items():
        reach.setdefault(name, set()).update(extra)
    return reach


def _reason_problems(row: Dict[str, str], reason: str, reasons: Set[str]) -> List[str]:
    path = row["Path"]
    if reason not in reasons:
        return [f"{path}: reason {reason} is not in the reasons table"]
    fits = REASON_FITS.get(reason)
    if fits is None:
        return [f"{path}: reason {reason} has no fit rule in REASON_FITS"]
    return [] if fits(row) else [f"{path}: reason {reason} does not fit a {row['Verb']} route with inputs {row['Inputs']}"]


def _tool_problems(row: Dict[str, str], tool: str, reach: Dict[str, Set[str]]) -> List[str]:
    from src.core.mcp import beast_mode, deprecated_tools, tools

    path, verbs = row["Path"], _verbs(row)
    if tool not in tools._TOOLS or tool in deprecated_tools.DEPRECATED:
        return [f"{path}: {tool} is not a registered, switched-on tool"]
    problems: List[str] = []
    handler = handler_reference(cp.first_ticked(row["Where"]))
    if handler not in reach.get(tool, set()):
        problems.append(f"{path}: {tool} does not reach {handler} (it reaches {sorted(reach.get(tool, set()))})")
    write = tool in tools.WRITE_TOOLS
    if verbs == {GET} and write:
        problems.append(f"{path}: {tool} is a write tool on a read-only route")
    if verbs != {GET} and (not write or tool not in beast_mode.ALWAYS_WAITS):
        problems.append(f"{path}: {tool} reaches a write route but is not a write on ALWAYS_WAITS")
    return problems


def mcp_column_problems(text: str) -> List[str]:
    reasons = {cp.first_ticked(r["Reason"]) for t in cp.tables(text) if t.header[:1] == ["Reason"] for r in t.rows}
    rows = cp.contract_rows(text, "1")
    if not rows or not reasons:
        return ["no route rows or no reasons: the checker read nothing"]
    reach, problems = tool_reach(), []
    for row in rows:
        none = MCP_NONE.match(row["MCP"])
        problems += _reason_problems(row, none.group(1), reasons) if none else _tool_problems(row, cp.first_ticked(row["MCP"]), reach)
    return problems
