
import asyncio
import importlib
import json
import sys
from typing import Any, Dict, List, Protocol, Sequence, Tuple


class ProbedPlugin(Protocol):

    _routes: Dict[str, Any]

    async def handle(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ...


async def inspect(plugin: ProbedPlugin, manifest: Dict[str, Any]) -> Tuple[List[str], List[str], List[str]]:
    problems: List[str] = []
    hello = await plugin.handle("initialize", {"settings": {}, "granted": []})
    listed = (await plugin.handle("tools/list", {}))["tools"]
    registered = {t["name"]: t for t in listed}
    declared = {t["name"]: t for t in manifest.get("tools", [])}
    for name in sorted(set(declared) - set(registered)):
        problems.append(f"tool {name} is declared in the manifest but the entry never registers it")
    for name in sorted(set(registered) - set(declared)):
        problems.append(f"tool {name} is registered by the entry but not declared in sidecar.tools (the host would not serve it)")
    for name in sorted(set(declared) & set(registered)):
        if declared[name].get("gate", "read") != registered[name].get("gate"):
            problems.append(f"tool {name}: the gate differs between the manifest and the entry")
    for name in sorted(set(manifest.get("routes", [])) - set(plugin._routes)):
        problems.append(f"route {name} is declared in the manifest but the entry never registers it")
    for name in sorted(set(plugin._routes) - set(manifest.get("routes", []))):
        problems.append(f"route {name} is registered by the entry but not declared in sidecar.routes (the host answers 404)")
    for family in hello.get("subscriptions", []):
        if family not in manifest.get("subscriptions", []):
            problems.append(f"event family {family} is handled by the entry but not declared in sidecar.subscriptions")
    return problems, sorted(registered), sorted(plugin._routes)


def main(argv: Sequence[str]) -> int:
    runtime_dir, code_dir, entry = argv[1], argv[2], argv[3]
    sys.path[:0] = [runtime_dir, code_dir]
    with open(code_dir + "/cplug.json", encoding="utf-8") as fh:
        manifest = json.load(fh)
    plugin = getattr(importlib.import_module(entry), "plugin", None)
    if plugin is None:
        print(json.dumps({"problems": ["the entry module has no `plugin`"], "tools": [], "routes": []}))
        return 3
    problems, tools, routes = asyncio.run(inspect(plugin, manifest))
    print(json.dumps({"problems": problems, "tools": tools, "routes": routes}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
