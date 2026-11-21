
from __future__ import annotations

import importlib
import inspect
import os
import re
import tempfile
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_apicontract_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_apicontract_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from tests.plugin_api import contract_parse as cp  # noqa: E402
from tests.plugin_api.mcp_column import mcp_column_problems  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "plugins" / "api-v1.md"
WEB_SDK = REPO / "web" / "src" / "plugins" / "sdk"
BRIDGE = REPO / "web" / "src" / "lib" / "cplug-ui" / "bridge.ts"
CPLUG_UI = REPO / "web" / "src" / "lib" / "cplug-ui"
HOST_SOURCES = (REPO / "src" / "plugins" / "runtime", REPO / "src" / "plugins" / "host")
ROUTE_MODULE_DIR = "src/plugins/host/"
OWNER_PREFIX = "/api/v1/cplug-owner/"
CATALOG_INSTALL = ("/api/v1/catalog/install", "/api/v1/catalog/install/", "/api/v1/catalog/installed")
WEB_SOURCE_GLOBS = ("*.ts", "*.svelte")
WEB_TEST_SUFFIX = ".test.ts"
EVENT_FRAME_PREFIXES = ("cplug", "resources")
PLUGIN_TOOL = re.compile(r"^(plugin|plugins|cplug|cplugs)_")
YES_NO = {True: "yes", False: "no"}
ON_OFF = {True: "on", False: "off"}
READ_WRITE = {True: "write", False: "read"}
ALL_TIERS = frozenset({"core", "builtin", "dev", "catalog"})
FIRST_PARTY_TIERS = frozenset({"builtin", "dev"})


def _missing_and_extra(documented: Set[str], coded: Set[str], what: str) -> List[str]:
    return ([f"{what} {n}: the doc names it, the code has none" for n in sorted(documented - coded)]
            + [f"{what} {n}: the code has it, the doc has no row" for n in sorted(coded - documented)])


def _rows(text: str, section: str) -> List[Dict[str, str]]:
    return cp.contract_rows(text, section)




def label_problems(text: str) -> List[str]:
    rows = [(t.section, r) for t in cp.tables(text) if cp.STABILITY_COLUMN in t.header for r in t.rows]
    if not rows:
        return ["no contract rows found: the checker read nothing"]
    return [f"{s}: {r} has stability {r[cp.STABILITY_COLUMN]!r}" for s, r in rows if r[cp.STABILITY_COLUMN] not in cp.STABILITY]


@lru_cache(maxsize=1)
def served_plugin_routes() -> Dict[Tuple[str, str], Tuple[str, str]]:
    from src.main import app
    from tests.test_route_auth_inventory import _walk

    found: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for kind, path, route, _inherited in _walk(app.routes):
        if kind != "http":
            continue
        bare, cite = cp.bare_path(path), cp.route_cite(route, REPO)
        if cite.startswith(ROUTE_MODULE_DIR) or bare.startswith(OWNER_PREFIX) or bare == CATALOG_INSTALL[0] or bare.startswith(CATALOG_INSTALL[1:]):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                found[(method, bare)] = (cite, cp.route_inputs(route))
    return found


def route_problems(text: str) -> List[str]:
    served = served_plugin_routes()
    rows = _rows(text, "1")
    if not rows or not served:
        return ["no route rows or no served routes: the checker read nothing"]
    documented: Dict[Tuple[str, str], Dict[str, str]] = {(v, cp.first_ticked(r["Path"])): r for r in rows for v in cp.doc_verbs(r["Verb"])}
    problems = _missing_and_extra({f"{m} {p}" for m, p in documented}, {f"{m} {p}" for m, p in served}, "route")
    for key, row in documented.items():
        if key in served:
            cite, inputs = served[key]
            if cp.first_ticked(row["Where"]) != cite:
                problems.append(f"{key}: the doc cites {row['Where']}, the handler is {cite}")
            if cp.first_ticked(row["Inputs"]) != inputs:
                problems.append(f"{key}: the doc's inputs are {row['Inputs']}, the route takes {inputs}")
    return problems




def _signed_rows(rows: List[Dict[str, str]], key: str, coded: Dict[str, Tuple[str, str]]) -> List[str]:
    documented = {cp.first_ticked(r[key]): r for r in rows}
    problems = _missing_and_extra(set(documented), set(coded), "name")
    for name, row in documented.items():
        if name in coded:
            kind, signature = coded[name]
            if row["Kind"] != kind:
                problems.append(f"{name}: the doc says {row['Kind']}, the code has a {kind}")
            if cp.first_ticked(row["Signature"]) != signature:
                problems.append(f"{name}: the doc's signature is {row['Signature']}, the code's is {signature}")
    return problems


def coded_ctx() -> Dict[str, Tuple[str, str]]:
    from src.plugins.sdk.context import CAPABILITY_GRANTS, CplugContext

    probe = CplugContext("probe", storage=object(), settings={}, notify=lambda n, k: None, log=object(), grants=frozenset(), capabilities={})
    out = {f"ctx.{n}": ("attribute", cp.NONE_CELL) for n in cp.public_instance_attrs(probe)}
    for name, raw in cp.public_members(CplugContext).items():
        kind = cp.member_kind(raw)
        out[f"ctx.{name}"] = (kind, f"ctx.{name}({cp.render_params(raw, drop_first=True)})" if kind == "method" else cp.NONE_CELL)
    out.update({f"ctx.{n}": ("capability", cp.NONE_CELL) for n in CAPABILITY_GRANTS})
    return out


def ctx_problems(text: str) -> List[str]:
    from src.plugins.sdk.context import CAPABILITY_GRANTS

    rows = _rows(text, "2.1")
    if not rows:
        return ["no ctx rows found: the checker read nothing"]
    problems = _signed_rows(rows, "Member", coded_ctx())
    for row in rows:
        name = cp.first_ticked(row["Member"]).removeprefix("ctx.")
        want = CAPABILITY_GRANTS.get(name, cp.NONE_CELL)
        if cp.first_ticked(row["Needs"]) != want:
            problems.append(f"ctx.{name}: the doc says it needs {row['Needs']}, the code says {want}")
    return problems


def _module_entry(name: str, value: Any, shown: str) -> Tuple[str, str]:
    kind = cp.module_kind(value)
    if kind == "function":
        return kind, f"{shown}({cp.render_params(value)})"
    return kind, cp.NONE_CELL


def server_sdk_problems(text: str) -> List[str]:
    import src.plugins.sdk as sdk

    rows = _rows(text, "2.2")
    if not rows:
        return ["no server SDK rows found: the checker read nothing"]
    return _signed_rows(rows, "Name", {n: _module_entry(n, getattr(sdk, n), n) for n in sdk.__all__})


def coded_sidecar_sdk() -> Dict[str, Tuple[str, str]]:
    import src.plugins.sdk_py as package
    from src.plugins.sdk_py import plugin, testing

    probes = {plugin.Plugin: plugin.Plugin(), plugin.Host: plugin.Host(lambda m, p: None), plugin.HostError: plugin.HostError(0, "probe"),
              testing.FakeHost: testing.FakeHost()}
    out: Dict[str, Tuple[str, str]] = {n: (cp.module_kind(getattr(plugin, n)), cp.NONE_CELL) for n in vars(plugin) if n.isupper()}
    for module, prefix in ((plugin, ""), (testing, "testing.")):
        for name, value in vars(module).items():
            if name.startswith("_") or getattr(value, "__module__", None) != module.__name__:
                continue
            shown = prefix + name
            if inspect.isfunction(value):
                out[shown] = _module_entry(name, value, shown)
            elif inspect.isclass(value):
                out[shown] = (cp.module_kind(value), f"{shown}({cp.render_params(value.__init__, drop_first=True)})")
                for member, raw in cp.public_members(value).items():
                    kind = cp.member_kind(raw)
                    sig = f"{shown}.{member}({cp.render_params(raw, drop_first=True)})" if kind == "method" else cp.NONE_CELL
                    out[f"{shown}.{member}"] = (kind, sig)
                out.update({f"{shown}.{a}": ("attribute", cp.NONE_CELL) for a in cp.public_instance_attrs(probes[value])})
    missing = set(package.__all__) - set(out)
    out.update({n: ("unlisted", cp.NONE_CELL) for n in missing})
    return out


def sidecar_sdk_problems(text: str) -> List[str]:
    rows = _rows(text, "2.3")
    if not rows:
        return ["no sidecar SDK rows found: the checker read nothing"]
    return _signed_rows(rows, "Name", coded_sidecar_sdk())


def host_method_problems(text: str) -> List[str]:
    from src.plugins.runtime.dispatch import HostDispatcher

    coded = set(re.findall(r'"([a-z_.]+)": self\._', inspect.getsource(HostDispatcher._table)))
    rows = _rows(text, "2.4")
    if not rows or not coded:
        return ["no host method rows or no dispatch table: the checker read nothing"]
    return _missing_and_extra({cp.first_ticked(r["Method"]) for r in rows}, coded, "host method")


def _host_sends(method: str) -> bool:
    needle = f'"{method}"'
    return any(needle in p.read_text() for root in HOST_SOURCES for p in root.rglob("*.py"))


def sidecar_call_problems(text: str) -> List[str]:
    from src.plugins.sdk_py.plugin import Plugin

    coded = set(re.findall(r'method == "([^"]+)"', inspect.getsource(Plugin.handle)))
    rows = _rows(text, "2.5")
    if not rows or not coded:
        return ["no sidecar call rows or no handle branches: the checker read nothing"]
    problems = _missing_and_extra({cp.first_ticked(r["Method"]) for r in rows}, coded, "call into a sidecar")
    for row in rows:
        method = cp.first_ticked(row["Method"])
        if row["Host sends"] != YES_NO[_host_sends(method)]:
            problems.append(f"{method}: the doc says the host sends it: {row['Host sends']}")
    return problems




def bridge_verb_problems(text: str) -> List[str]:
    match = re.search(r"export const VERBS = \[(.*?)\]", BRIDGE.read_text())
    coded = set(re.findall(r"'([a-z_.]+)'", match.group(1))) if match else set()
    rows = _rows(text, "3.1")
    if not rows or not coded:
        return ["no bridge verb rows or no VERBS: the checker read nothing"]
    return _missing_and_extra({cp.first_ticked(r["Verb"]) for r in rows}, coded, "bridge verb")


def bridge_event_problems(text: str) -> List[str]:
    coded = set(re.findall(r"postMessage\(\{ verb: '([a-z_.]+)'", BRIDGE.read_text()))
    for path in [p for ext in WEB_SOURCE_GLOBS for p in CPLUG_UI.rglob(ext) if not p.name.endswith(WEB_TEST_SUFFIX)]:
        coded |= set(re.findall(r"bridge\.send\('([a-z_.]+)'", path.read_text()))
    rows = _rows(text, "3.2")
    if not rows or not coded:
        return ["no bridge event rows or no events: the checker read nothing"]
    return _missing_and_extra({cp.first_ticked(r["Event"]) for r in rows}, coded, "bridge event")


def web_sdk_problems(text: str) -> List[str]:
    coded = cp.sdk_modules(WEB_SDK)
    rows = _rows(text, "3.3")
    if not rows or not coded:
        return ["no web SDK rows or no modules: the checker read nothing"]
    documented = {cp.first_ticked(r["Module"]): set(cp.ticked(r["Exports"])) for r in rows}
    problems = _missing_and_extra(set(documented), set(coded), "web SDK module")
    for module in set(documented) & set(coded):
        problems += _missing_and_extra(documented[module], coded[module], f"{module} export")
    return problems




def _resolve(reference: str) -> Any:
    module, _, dotted = reference.partition(":")
    value: Any = importlib.import_module(module)
    for part in dotted.split("."):
        value = getattr(value, part)
    return value.value if isinstance(value, Enum) else value


def _topic_example() -> str:
    from src.plugins.host import runtime

    for d in runtime.definitions():
        for name in d.manifest.surfaces.topics:
            return runtime.Host.family(d.id, name)
    raise LookupError("no shipped plugin declares a topic")


def event_problems(text: str) -> List[str]:
    from src.plugins.host.runtime import CPLUGS_TOPIC
    from src.plugins.runtime.process import FEED_GRANTS
    from src.models.websocket import WSMessageType

    rows = _rows(text, "4")
    if not rows:
        return ["no event rows found: the checker read nothing"]
    problems: List[str] = []
    for row in rows:
        name, where = cp.first_ticked(row["Name"]), cp.first_ticked(row["Where"])
        try:
            value = _resolve(where)
        except (ImportError, AttributeError) as exc:
            problems.append(f"{name}: {where} does not resolve ({type(exc).__name__})")
            continue
        if callable(value):
            pattern = re.escape(name).replace(re.escape("<id>"), r"[^.:]+").replace(re.escape("<name>"), r"[^.:]+")
            if not re.fullmatch(pattern, _topic_example()):
                problems.append(f"{name}: {where} builds {_topic_example()}, not that shape")
        elif not (value == name or (isinstance(value, dict) and name in value)):
            problems.append(f"event {name}: the doc names it, the code has none ({where} is {value!r})")
    frames = {m.value for m in WSMessageType if m.value.startswith(EVENT_FRAME_PREFIXES)}
    coded = {CPLUGS_TOPIC, *frames, *FEED_GRANTS}
    documented = {cp.first_ticked(r["Name"]) for r in rows}
    return problems + [f"event {n}: the code has it, the doc has no row" for n in sorted(coded - documented)]


def mcp_tool_problems(text: str) -> List[str]:
    from src.core.mcp import beast_mode, deprecated_tools, tools

    rows = _rows(text, "5.1")
    coded = {n for n in tools._TOOLS if PLUGIN_TOOL.match(n)}
    if not rows or not coded:
        return ["no MCP tool rows or no plugin tools: the checker read nothing"]
    specs = {s.name: s.route for m in tools._ROUTE_MODULES for s in getattr(m, "SPECS", ())}
    documented = {cp.first_ticked(r["Tool"]): r for r in rows}
    problems = _missing_and_extra(set(documented), coded, "MCP tool")
    for name, row in documented.items():
        if name not in coded:
            continue
        write = name in tools.WRITE_TOOLS
        checks = ((row["Kind"], READ_WRITE[write], "kind"), (row["Default"], ON_OFF[name not in deprecated_tools.DEPRECATED], "default"),
                  (cp.first_ticked(row["Route"]), specs.get(name, cp.NONE_CELL), "route"))
        problems += [f"{name}: the doc's {what} is {doc}, the code's is {code}" for doc, code, what in checks if doc != code]
        if write and name not in beast_mode.ALWAYS_WAITS:
            problems.append(f"{name}: a plugin write that is not on ALWAYS_WAITS")
    return problems


def gate_problems(text: str) -> List[str]:
    from src.plugins.host.sidecar_manifest import TOOL_GATES
    from src.plugins.sdk.definition import GATES

    rows = _rows(text, "5.2")
    if not rows:
        return ["no gate rows found: the checker read nothing"]
    documented = {cp.first_ticked(r["Gate"]): r for r in rows}
    problems = _missing_and_extra(set(documented), set(GATES), "gate")
    return problems + [f"gate {g}: Sidecar says {r['Sidecar']}" for g, r in documented.items() if r["Sidecar"] != YES_NO[g in TOOL_GATES]]


def permission_problems(text: str) -> List[str]:
    from src.plugins.sdk.permission_registry import REGISTRY

    rows = _rows(text, "6")
    if not rows:
        return ["no permission rows found: the checker read nothing"]
    coded = {p.name: p for p in REGISTRY}
    documented = {cp.first_ticked(r["Permission"]): r for r in rows}
    problems = _missing_and_extra(set(documented), set(coded), "permission")
    for name in set(documented) & set(coded):
        row, perm = documented[name], coded[name]
        holders = {ALL_TIERS: "all", FIRST_PARTY_TIERS: "first-party"}.get(frozenset(perm.tiers), "/".join(sorted(perm.tiers)))
        if (row["Risk"], row["Holders"]) != (perm.risk, holders):
            problems.append(f"{name}: the doc says {row['Risk']}/{row['Holders']}, the registry says {perm.risk}/{holders}")
    return problems


CHECKS: Dict[str, Callable[[str], List[str]]] = {
    "1": route_problems, "2.1": ctx_problems, "2.2": server_sdk_problems, "2.3": sidecar_sdk_problems, "2.4": host_method_problems,
    "2.5": sidecar_call_problems, "3.1": bridge_verb_problems, "3.2": bridge_event_problems, "3.3": web_sdk_problems,
    "4": event_problems, "5.1": mcp_tool_problems, "5.2": gate_problems, "6": permission_problems,
}


def mutate_first_row(text: str, section: str, drop: bool) -> str:
    lines, current, header = text.splitlines(), "", None
    for i, line in enumerate(lines):
        heading = re.match(r"^#{2,3} (\d+(?:\.\d+)?)\b", line)
        if heading:
            current, header = heading.group(1), None
            continue
        in_section = current == section or current.startswith(section + ".")
        if not line.startswith("|"):
            header = None
        elif header is None:
            header = line
        elif in_section and cp.STABILITY_COLUMN in header and not set(line.replace("|", "").strip()) <= set("-: "):
            changed = [] if drop else [re.sub(r"`([^`]+)`", r"`\1_zz`", line, count=1)]
            return "\n".join(lines[:i] + changed + lines[i + 1:]) + "\n"
    raise LookupError(f"section {section} has no contract row")


def test_every_contract_row_carries_a_stability_label():
    assert label_problems(DOC.read_text()) == []


@pytest.mark.parametrize("section", sorted(CHECKS))
def test_the_doc_matches_the_code(section: str):
    assert CHECKS[section](DOC.read_text()) == []


def test_every_route_names_its_mcp_tool_or_a_reason():
    assert mcp_column_problems(DOC.read_text()) == []


@pytest.mark.parametrize("section", sorted(CHECKS))
def test_each_check_goes_red_on_a_renamed_or_dropped_row(section: str):
    text = DOC.read_text()
    renamed, dropped = CHECKS[section](mutate_first_row(text, section, drop=False)), CHECKS[section](mutate_first_row(text, section, drop=True))
    assert any("the doc names it, the code has none" in p for p in renamed), renamed
    assert any("the doc has no row" in p for p in dropped), dropped


MCP_RED_CASES = (
    ("| `plugin_restart` | experimental |", "| `plugins_list` | experimental |", "a read tool on a write route"),
    ("| `plugin_stop` | experimental |", "| `plugin_sideload_remove` | experimental |", "a write tool that does not reach the kill route"),
    ("| `plugin_capability_calls_list` | experimental |", "| `plugin_restart` | experimental |", "a write tool on a read route"),
    ("| `plugin_requests_list` | experimental |", "| `plugin_capability_calls_list` | experimental |", "a read tool reaching another route"),
    ("| none: owner-only |", "| none: because |", "a reason not in the table"),
    ("| none: owner-only |", "| none: ui-asset |", "a reason that does not fit the purge route"),
    ("| `{confirm_dependents, consent, enabled, grants, revision, settings}` | none: consent |",
     "| `{confirm_dependents, consent, enabled, grants, revision, settings}` | none: ui-asset |", "ui-asset on the enable route"),
    ("| `{value}` | none: credentials |", "| `{value}` | none: platform |", "platform off the catalog"),
)


def test_the_label_check_goes_red():
    text = DOC.read_text()
    assert label_problems(text.replace("| `ctx.id` | attribute | - | - | stable |", "| `ctx.id` | attribute | - | - | solid |"))


@pytest.mark.parametrize("old,new,why", MCP_RED_CASES, ids=[c[2] for c in MCP_RED_CASES])
def test_the_mcp_check_goes_red(old: str, new: str, why: str):
    """Each wrong MCP cell goes red. Inputs: the cell, its replacement, and what is wrong with it."""
    text = DOC.read_text()
    assert text.count(old) >= 1, f"the red case for {why} no longer matches the doc"
    assert mcp_column_problems(text.replace(old, new, 1)), why
