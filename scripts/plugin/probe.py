
import asyncio
import importlib
import json
import os
import sys
import tomllib
from typing import Any, Dict, List, Protocol, Sequence, Tuple


class ProbedPlugin(Protocol):

    _routes: Dict[str, Any]

    async def handle(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ...


def _load_v2_manifest(code_dir: str) -> Dict[str, Any]:
    toml_path = os.path.join(code_dir, "carnivore.toml")
    if os.path.isfile(toml_path):
        with open(toml_path, "rb") as fh:
            return tomllib.load(fh)
    json_path = os.path.join(code_dir, "carnivore.json")
    with open(json_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("schema") != 2:
        raise ValueError("carnivore.json must declare schema = 2")
    return doc


async def inspect(plugin: ProbedPlugin, manifest: Dict[str, Any]) -> Tuple[List[str], List[str], List[str]]:
    problems: List[str] = []
    hello = await plugin.handle("initialize", {"settings": {}, "granted": []})
    listed = (await plugin.handle("tools/list", {}))["tools"]
    registered = {t["name"]: t for t in listed}
    mcp_block = manifest.get("mcp") if isinstance(manifest.get("mcp"), dict) else {}
    declared = {t["name"]: t for t in mcp_block.get("tools", []) if isinstance(t, dict) and "name" in t}
    for name in sorted(set(declared) - set(registered)):
        problems.append(f"tool {name} is declared in the manifest but the entry never registers it")
    for name in sorted(set(registered) - set(declared)):
        problems.append(f"tool {name} is registered by the entry but not declared in mcp.tools (the host would not serve it)")
    for name in sorted(set(declared) & set(registered)):
        if declared[name].get("gate", "read") != registered[name].get("gate"):
            problems.append(f"tool {name}: the gate differs between the manifest and the entry")
    ui_block = manifest.get("ui") if isinstance(manifest.get("ui"), dict) else {}
    declared_routes = list(ui_block.get("routes", []))
    for name in sorted(set(declared_routes) - set(plugin._routes)):
        problems.append(f"route {name} is declared in the manifest but the entry never registers it")
    for name in sorted(set(plugin._routes) - set(declared_routes)):
        problems.append(f"route {name} is registered by the entry but not declared in ui.routes (the host answers 404)")
    events_block = manifest.get("events") if isinstance(manifest.get("events"), dict) else {}
    webhooks_block = manifest.get("webhooks") if isinstance(manifest.get("webhooks"), dict) else {}
    declared_subs = set(events_block.get("on", [])) | {f"webhook.{k}" for k in webhooks_block}
    for family in hello.get("subscriptions", []):
        if family not in declared_subs:
            problems.append(f"event family {family} is handled by the entry but not declared in events.on")
    return problems, sorted(registered), sorted(plugin._routes)


def main(argv: Sequence[str]) -> int:
    runtime_dir, code_dir, entry = argv[1], argv[2], argv[3]
    sys.path[:0] = [runtime_dir, code_dir]
    manifest = _load_v2_manifest(code_dir)
    plugin = getattr(importlib.import_module(entry), "plugin", None)
    if plugin is None:
        print(json.dumps({"problems": ["the entry module has no `plugin`"], "tools": [], "routes": []}))
        return 3
    problems, tools, routes = asyncio.run(inspect(plugin, manifest))
    print(json.dumps({"problems": problems, "tools": tools, "routes": routes}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
