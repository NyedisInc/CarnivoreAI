
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

SERVED_ROOTS = ("client/js", "client/css", "client/style-guide", "client/index.html", "client/style-guide.html", "web/src")
SKIP_SUFFIXES = (".test.ts", ".test.js", ".spec.ts")


COMMENT_STARTS = ("//", "*", "/*", "<!--", "#")
STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def served_files(root: Path, suffixes: Tuple[str, ...]) -> List[Path]:
    found: List[Path] = []
    for rel in SERVED_ROOTS:
        base = root / rel
        files = [base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []
        found += [f for f in files if f.is_file() and f.suffix in suffixes and not f.name.endswith(SKIP_SUFFIXES)]
    return found


def string_key_hits(root: Path, namespace: str) -> List[str]:
    literal = re.compile(r"""['"`][^'"`\n]*""" + re.escape(namespace) + r"""[^'"`\n]*['"`]""")
    hits = []
    for f in served_files(root, (".js", ".ts", ".svelte", ".json")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.lstrip().startswith(COMMENT_STARTS) and literal.search(line):
                hits.append(str(f.relative_to(root)))
                break
    return hits


def style_hits(root: Path, prefix: str) -> List[str]:
    needle = re.compile(r"\." + re.escape(prefix) + r"-[\w-]")
    hits = []
    for f in served_files(root, (".css", ".svelte", ".html")):
        text = f.read_text(encoding="utf-8", errors="replace")
        css = text if f.suffix == ".css" else "\n".join(STYLE_BLOCK.findall(text))
        if needle.search(CSS_COMMENT.sub("", css)):
            hits.append(str(f.relative_to(root)))
    return hits


def main(arg: Dict[str, object]) -> Dict[str, Tuple[bool, str]]:
    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from src.api.auth import require_auth  # noqa: PLC0415
    from src.core.mcp import tools  # noqa: PLC0415
    from src.cplugs.host import mcp as cplug_mcp, routes as host_routes, runtime, state as owner_state  # noqa: PLC0415
    from src.config import settings  # noqa: PLC0415

    pid = str(arg["plugin_id"])
    state_dir = Path(settings.get_state_dir())
    app = FastAPI()
    host = runtime.install(app, state_dir)
    host.publish = lambda topic: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "gate"}
    client = TestClient(app, raise_server_exceptions=False)
    out: Dict[str, Tuple[bool, str]] = {}
    with client:
        rows = {r["id"]: r for r in client.get("/api/v1/cplugs").json()["cplugs"]}
        out["listed_as_removed"] = (rows.get(pid, {}).get("state") == "removed", f"row: {rows.get(pid)}")
        row = client.get(f"/api/v1/cplugs/{pid}")
        out["row_404"] = (row.status_code == 404, f"GET /cplugs/{pid} -> {row.status_code}")
        put = client.put(f"/api/v1/cplugs/{pid}", json={"revision": 0, "enabled": True})
        out["enable_404"] = (put.status_code == 404, f"PUT enable -> {put.status_code}")
        bad = []
        for route in arg["routes"]:  # type: ignore[union-attr]
            path = re.sub(r"\{[^}]+\}", "x", f"/api/v1/cplugs/{pid}{route}")
            code = client.get(path).status_code
            if code != 404:
                bad.append(f"{route} -> {code}")
        out["routes_404"] = (not bad, f"{len(arg['routes'])} route(s) checked; not 404: {bad[:4]}")  # type: ignore[arg-type]
        names = list(arg["tools"])  # type: ignore[arg-type]
        offered = {t["name"] for t in tools.tool_definitions()}
        still = [n for n in names if n in offered or n in cplug_mcp.TOOLS or n in tools.tool_names()]
        out["tools_gone"] = (not still, f"{len(names)} tool(s) checked; still present: {still[:4]}")
        price = client.post(f"/api/v1/cplugs/{pid}/purge", json={"dry_run": True})
        out["purge_priced"] = (price.status_code == 200 and price.json().get("files", 0) >= 1, f"dry run -> {price.status_code} {price.text[:140]}")
        done = client.post(f"/api/v1/cplugs/{pid}/purge", json={"dry_run": False, "confirm_token": price.json().get("confirm_token", "")}) if price.status_code == 200 else price
        out["purge_runs"] = (done.status_code == 200, f"purge -> {done.status_code} {done.text[:140] if done.status_code != 200 else ''}")
    left = [p for p in arg["removed"] if Path(p).exists()]  # type: ignore[union-attr]
    left += [str(host.folder(pid))] if host.folder(pid).exists() else []
    out["files_gone"] = (not left, f"left behind: {left[:4]}" if left else "seeded files and the plugin folder are gone")
    lost = [p for p in arg["kept"] if not Path(p).exists()]  # type: ignore[union-attr]
    out["kept_stores_stay"] = (not lost, f"destroyed: {lost[:3]}" if lost else f"{len(arg['kept'])} kept file(s) still there")  # type: ignore[arg-type]
    out["state_entry_gone"] = (pid not in owner_state.stored_ids(state_dir), "state.json entry")
    root = Path.cwd()
    key_hits = string_key_hits(root, str(arg["namespace"]))
    out["strings_not_served"] = (not key_hits, f"{arg['namespace']} still in: {key_hits[:4]}" if key_hits else f"no {arg['namespace']} key in the served sources")
    prefix = str(arg.get("css_prefix") or "")
    css_hits = style_hits(root, prefix) if prefix else []
    out["styles_not_served"] = (not css_hits, f".{prefix}- still in: {css_hits[:4]}" if css_hits else (f"no .{prefix}- class in the served sources" if prefix else "plugin declares no css_prefix"))
    return out


if __name__ == "__main__":
    result = main(json.loads(sys.argv[1]))
    print(json.dumps({k: [v[0], v[1]] for k, v in result.items()}))
