
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.mcp import tools as mcp_tools
from src.cplugs.host import data_roots, routes as host_routes, runtime, state as owner_state
from src.cplugs.host import mcp as cplug_mcp
from src.cplugs.sdk.definition import CplugDefinition
from tests.helpers.catalog_text import CATALOG_PATH, REPO_ROOT, slice_paths
from tests.python.cplugs.owner import turn_on
from tests.python.cplugs.removability import KEY_LINE, assert_no_dangling_assets
from scripts.gate.tree_copy import NOT_REMOVABLE

CHECKS: Tuple[str, ...] = (
    "enable", "use", "tools_listed_on", "disable", "routes_refused_off", "tools_unlisted_off",
    "purge_priced", "purge_runs", "files_gone", "kept_stores_stay", "state_entry_gone", "back_to_default",
    "strings_styles_own", "re_enable", "use_again",
)
PASS, FAIL, NA = "pass", "fail", "na"


@dataclass
class Outcome:

    plugin_id: str
    checks: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    use_kind: str = ""

    def record(self, name: str, ok: bool, detail: str = "") -> bool:
        assert name in CHECKS, name
        self.checks[name] = (PASS if ok else FAIL, detail)
        return ok

    def not_applicable(self, name: str, why: str) -> None:
        assert name in CHECKS and why, name
        self.checks[name] = (NA, why)

    def skipped(self, name: str, because: str) -> None:
        self.checks[name] = (FAIL, f"not reached: {because}")


def make_client(state_dir: Path) -> Tuple[TestClient, runtime.Host]:
    app = FastAPI()
    host = runtime.install(app, state_dir)
    host.publish = lambda topic: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "gate"}
    return TestClient(app, raise_server_exceptions=False), host


def read_routes(d: CplugDefinition) -> List[Tuple[str, Dict[str, str]]]:
    out = []
    for r in (d.router.routes if d.router else ()):
        if "GET" in getattr(r, "methods", ()) and "{" not in r.path:
            out.append(("/api/v1" + r.path, {q.name: "gate-probe" for q in r.dependant.query_params if q.field_info.is_required()}))
    return out


HOST_CODES = frozenset({"cplug_disabled", "cplug_unknown", "cplug_unavailable"})


def served(answer: Any) -> bool:
    if answer.status_code == 200:
        return True
    if not 400 <= answer.status_code < 500 or answer.status_code == 401:
        return False
    detail = answer.json().get("detail") if answer.headers.get("content-type", "").startswith("application/json") else None
    return isinstance(detail, dict) and bool(detail.get("code")) and detail["code"] not in HOST_CODES


def use_route(client: TestClient, d: CplugDefinition) -> Tuple[Optional[str], str]:
    seen: List[str] = []
    for path, query in read_routes(d):
        answer = client.get(path, params=query)
        seen.append(f"{path[len('/api/v1'):]} -> {answer.status_code}")
        if served(answer):
            return path, "; ".join(seen)
    return None, "; ".join(seen)


def listed_tools() -> List[str]:
    return [t["name"] for t in mcp_tools.tool_definitions()]


def _enable(client: TestClient, base: str, d: CplugDefinition) -> Dict[str, Any]:
    row = client.get(base).json()
    answer = client.put(base, json={"revision": row["revision"], "enabled": True, "grants": {"app": list(d.manifest.permissions)}})
    body = answer.json()
    body["_status"] = answer.status_code
    return body


def _disable(client: TestClient, base: str) -> Dict[str, Any]:
    row = client.get(base).json()
    answer = client.put(base, json={"revision": row["revision"], "enabled": False, "confirm_dependents": True})
    body = answer.json()
    body["_status"] = answer.status_code
    return body


def _stores(d: CplugDefinition, state_dir: Path, settings: Dict[str, Any]) -> List[Tuple[Any, Optional[Path]]]:
    return [(decl, data_roots.decl_root(state_dir, d.id, decl, settings)) for decl in (d.manifest.data or ())]


def seed(client: TestClient, host: runtime.Host, d: CplugDefinition, work: Path) -> Dict[str, List[Path]]:
    base = f"/api/v1/cplugs/{d.id}"
    written: Dict[str, List[Path]] = {"removed": [], "kept": []}
    fields = (d.manifest.settings_schema or {}).get("fields", {})
    for decl in d.manifest.data or ():
        if decl.root_setting and decl.root_setting in fields:
            target = work / "owner-folders" / f"{d.id}-{decl.root_setting}"
            target.parent.mkdir(parents=True, exist_ok=True)
            row = client.get(base).json()
            saved = client.put(base, json={"revision": row["revision"], "settings": {decl.root_setting: str(target)}})
            assert saved.status_code == 200, f"{d.id}: could not place {decl.root_setting}: {saved.text[:200]}"
    settings = owner_state.get(host.state_dir, d.manifest).settings
    own = host.folder(d.id)
    own.mkdir(parents=True, exist_ok=True)
    (own / "gate-seed.bin").write_bytes(b"x" * 7)
    written["removed"].append(own / "gate-seed.bin")
    for decl, root in _stores(d, host.state_dir, settings):
        if root is None:
            continue
        if decl.kind == "db" or decl.kind == "file":
            root.parent.mkdir(parents=True, exist_ok=True)
            root.write_bytes(b"s" * 5)
            marker = root
        else:
            root.mkdir(parents=True, exist_ok=True)
            marker = root / "gate-seed.bin"
            marker.write_bytes(b"s" * 5)
        written["removed" if decl.path or not decl.outlives_purge else "kept"].append(marker)
    for rel in d.manifest.owns.files:
        target = host.state_dir / rel
        target.mkdir(parents=True, exist_ok=True)
        (target / "gate-seed.bin").write_bytes(b"y" * 3)
        kept_by_store = any(str(target).startswith(str(r)) or str(r).startswith(str(target)) for decl, r in _stores(d, host.state_dir, settings)
                            if r is not None and decl.outlives_purge)
        written["kept" if kept_by_store else "removed"].append(target / "gate-seed.bin")
    return written


def declared_prefix(plugin_id: str) -> str:
    raw = json.loads((REPO_ROOT / "src" / "cplugs" / plugin_id / "cplug.json").read_text(encoding="utf-8"))
    return str(raw.get("css_prefix", ""))


@dataclass
class Installed:

    state_dir: Path
    written: Dict[str, List[Path]]
    routes: List[str]
    tools: List[str]
    namespace: str
    css_prefix: str


def install_and_leave(plugin_id: str, work: Path) -> Installed:
    d = runtime.find(plugin_id)
    assert d is not None, plugin_id
    state_dir = work / "state"
    client, host = make_client(state_dir)
    base = f"/api/v1/cplugs/{plugin_id}"
    with client:
        for needed in d.manifest.requires:
            turn_on(host, needed)
        answer = _enable(client, base, d)
        assert answer["_status"] == 200, f"{plugin_id} would not enable: {answer}"
        use_route(client, d)
        written = seed(client, host, d, work)
        off = _disable(client, base)
        assert off["_status"] == 200, f"{plugin_id} would not disable: {off}"
    return Installed(state_dir, written, list(d.manifest.owns.routes), sorted(d.tools), f"cplug.{plugin_id}.", declared_prefix(plugin_id))


def strings_styles_check(d: CplugDefinition) -> Tuple[Optional[bool], str]:
    if d.id in NOT_REMOVABLE:
        return None, NOT_REMOVABLE[d.id]
    try:
        assert_no_dangling_assets(d.id)
        missing = [p for p in d.manifest.owns.styles if not (REPO_ROOT / "web" / "src" / "cplugs" / d.id / p).is_file()]
        assert not missing, f"owns.styles files missing: {missing}"
    except AssertionError as exc:
        return False, str(exc)[:300]
    shared = {k for k in KEY_LINE.findall(CATALOG_PATH.read_text(encoding="utf-8")) if k.startswith(f"cplug.{d.id}.")}
    own = slice_paths().get(d.id)
    return (not shared and own is not None), f"shared catalog holds {sorted(shared)[:3]}" if shared else f"slice {own.name if own else 'missing'}"


def run_cycle(plugin_id: str, work: Path) -> Outcome:
    d = runtime.find(plugin_id)
    assert d is not None, plugin_id
    out = Outcome(plugin_id)
    state_dir = work / "state"
    client, host = make_client(state_dir)
    base = f"/api/v1/cplugs/{plugin_id}"
    m = d.manifest
    tool_names = sorted(d.tools)
    has_route = bool(read_routes(d))
    with client:
        default_row = client.get(base).json()
        for needed in m.requires:
            turn_on(host, needed)
        answer = _enable(client, base, d)
        out.record("enable", answer["_status"] == 200 and answer.get("enabled") is True, f"PUT enable -> {answer['_status']} {str(answer.get('detail', ''))[:160]}")
        if out.checks["enable"][0] != PASS:
            for name in CHECKS[1:]:
                out.skipped(name, "enable failed")
            return out
        route = None
        if has_route:
            route, seen = use_route(client, d)
            out.use_kind = f"GET {route[len('/api/v1'):]}" if route else "GET (none served)"
            out.record("use", route is not None, seen)
        else:
            row = client.get(base).json()
            out.use_kind = "plugin row (declares no read route)"
            out.record("use", row.get("state") == "active" and row.get("enabled") is True, f"state={row.get('state')} enabled={row.get('enabled')}")
        if tool_names:
            offered = set(listed_tools())
            missing = [t for t in tool_names if t not in offered or not cplug_mcp.available(t)]
            out.record("tools_listed_on", not missing, f"missing from tools/list: {missing}" if missing else f"{len(tool_names)} tool(s) listed")
        else:
            out.not_applicable("tools_listed_on", "declares no MCP tools")
        written = seed(client, host, d, work)
        assert plugin_id in owner_state.stored_ids(state_dir)
        off = _disable(client, base)
        out.record("disable", off["_status"] == 200 and off.get("enabled") is False, f"PUT disable -> {off['_status']} {str(off.get('detail', ''))[:160]}")
        if has_route and route:
            refused = client.get(route, params=dict(read_routes(d))[route])
            code = refused.json().get("detail", {}).get("code") if refused.headers.get("content-type", "").startswith("application/json") else None
            out.record("routes_refused_off", refused.status_code == 409 and code == "cplug_disabled", f"{out.use_kind} while off -> {refused.status_code} {code}")
        elif has_route:
            out.record("routes_refused_off", False, "no declared read route was served while on, so the off answer cannot be compared")
        else:
            out.not_applicable("routes_refused_off", "declares no read routes")
        if tool_names:
            offered = set(listed_tools())
            still = [t for t in tool_names if t in offered or cplug_mcp.available(t)]
            out.record("tools_unlisted_off", not still, f"still offered while off: {still}" if still else "none offered while off")
        else:
            out.not_applicable("tools_unlisted_off", "declares no MCP tools")
        price = client.post(f"{base}/purge", json={"dry_run": True})
        priced = price.status_code == 200 and price.json().get("files", 0) >= 1 and all(p.exists() for p in written["removed"] + written["kept"])
        kept_decl = sorted(decl.id for decl in (m.data or ()) if decl.outlives_purge)
        got_kept = sorted(r["id"] for r in price.json().get("kept_stores", [])) if price.status_code == 200 else None
        out.record("purge_priced", priced and got_kept == kept_decl, f"dry run -> {price.status_code}; files={price.json().get('files') if price.status_code == 200 else '-'}; kept_stores {got_kept} vs declared {kept_decl}")
        stale = client.post(f"{base}/purge", json={"dry_run": False, "confirm_token": "not-the-token"})
        done = client.post(f"{base}/purge", json={"dry_run": False, "confirm_token": price.json().get("confirm_token", "")})
        out.record("purge_runs", stale.status_code == 409 and done.status_code == 200, f"stale token -> {stale.status_code}; confirmed purge -> {done.status_code} {done.text[:160] if done.status_code != 200 else ''}")
        left = [str(p) for p in written["removed"] if p.exists()]
        left += [str(host.folder(plugin_id))] if host.folder(plugin_id).exists() else []
        out.record("files_gone", not left, f"left behind after purge: {left[:4]}" if left else f"{len(written['removed'])} seeded file(s) gone, plugin folder gone")
        gone_kept = [str(p) for p in written["kept"] if not p.exists()]
        if written["kept"]:
            out.record("kept_stores_stay", not gone_kept, f"purge destroyed a kept store: {gone_kept[:3]}" if gone_kept else f"{len(written['kept'])} kept file(s) still there")
        else:
            out.not_applicable("kept_stores_stay", "declares no purge: kept store")
        out.record("state_entry_gone", plugin_id not in owner_state.stored_ids(state_dir), "state.json still names it" if plugin_id in owner_state.stored_ids(state_dir) else "no state.json entry")
        after = client.get(base).json()
        same = {k: after.get(k) for k in ("enabled", "state", "revision", "settings", "storage_bytes")} == {k: default_row.get(k) for k in ("enabled", "state", "revision", "settings", "storage_bytes")}
        out.record("back_to_default", same, "row equals a never-touched install's" if same else f"row differs from default: {({k: (default_row.get(k), after.get(k)) for k in ('enabled', 'state', 'revision', 'settings', 'storage_bytes') if default_row.get(k) != after.get(k)})}")
        ok, detail = strings_styles_check(d)
        if ok is None:
            out.not_applicable("strings_styles_own", f"not removable yet: {detail}")
        else:
            out.record("strings_styles_own", ok, detail)
        if after.get("enabled"):
            _disable(client, base)
        again = _enable(client, base, d)
        out.record("re_enable", again["_status"] == 200 and again.get("enabled") is True, f"PUT enable after purge -> {again['_status']} {str(again.get('detail', ''))[:160]}")
        if route:
            used = client.get(route, params=dict(read_routes(d))[route])
            ok = served(used) and (not tool_names or all(t in set(listed_tools()) for t in tool_names))
            out.record("use_again", ok, f"{out.use_kind} -> {used.status_code}; tools back: {not tool_names or ok}")
        else:
            row = client.get(base).json()
            out.record("use_again", row.get("state") == "active", f"state={row.get('state')}")
    return out


def table(outcomes: List[Outcome]) -> str:
    short = {PASS: "pass", FAIL: "FAIL", NA: "n/a"}
    head = "plugin".ljust(14) + " ".join(c[:10].ljust(10) for c in CHECKS)
    rows = [head]
    for o in outcomes:
        rows.append(o.plugin_id.ljust(14) + " ".join(short[o.checks.get(c, (FAIL, ''))[0]].ljust(10) for c in CHECKS))
    return "\n".join(rows)


def dump(outcomes: List[Outcome], path: Path) -> None:
    path.write_text(json.dumps({o.plugin_id: {"use": o.use_kind, "checks": o.checks} for o in outcomes}, indent=1), encoding="utf-8")
