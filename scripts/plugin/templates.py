
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from scripts.plugin import check
from src.core.catalog.plugin_pack import FIELD_FLOOR

TEMPLATES = ("minimal", "sidecar", "page")
_DEFAULT_AUTHOR = "me"


class TemplateError(ValueError):
    pass


def _entry(name: str, body: str) -> str:
    return f'"""The {name} entry: handlers the host calls over its sandboxed pipe."""\n\nfrom __future__ import annotations\n\nfrom typing import Any, Dict\n\nfrom cplug_sdk import Plugin\n\nplugin = Plugin()\n{body}'


_TOOL = '''

@plugin.tool("{name}_hello", "Says hello. Reads nothing and changes nothing.", {{"type": "object", "properties": {{}}, "additionalProperties": False}}, gate="read")
async def hello(args: Dict[str, Any], caller: Any) -> str:
    """The hello tool. Inputs: args; caller. Output: the text hello."""
    return "hello"
'''
_ROUTE = '''

@plugin.route("status")
async def status(request: Dict[str, Any]) -> Dict[str, Any]:
    """The status route. Inputs: request. Output: {status, body}."""
    return {"status": 200, "body": {"ok": True}}
'''
_TEST = '''"""Smoke test for {name}: the handlers answer without a host (`plugin test` runs this beside the manifest checks)."""

import asyncio

from cplug_sdk.testing import FakeHost, attach

import {name}_main as entry


def test_hello_answers() -> None:
    attach(entry.plugin, FakeHost())
    assert asyncio.run(entry.plugin.handle("tools/call", {{"name": "{name}_hello", "arguments": {{}}}}))["content"][0]["text"] == "hello"
'''
_VIEW = "<!doctype html>\n<meta charset=\"utf-8\">\n<title>{name}</title>\n<p>{name} page</p>\n"


def _manifest(name: str, template: str, author: str) -> Dict[str, Any]:
    doc: Dict[str, Any] = {"name": name, "id": name, "description": f"The {name} plugin.", "version": "0.1.0", "author": author, "license": "MIT",
                           "permissions": [], "engines": {"carnivore": f">={FIELD_FLOOR}"}, "sidecar": {"entry": f"{name}_main.py"}}
    if template != "minimal":
        doc["sidecar"].update(routes=["status"], tools=[{"name": f"{name}_hello", "description": "Says hello. Reads nothing and changes nothing.",
                                                         "gate": "read", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}])
    if template == "page":
        doc["sidecar"]["views"] = [{"name": "face", "surfaces": ["panel"], "files": ["index.html"]}]
        doc.update(page={"menu": "face", "main": "face"}, topics=["changed"])
    return doc


def scaffold(dest: Path, name: str, template: str, author: str = _DEFAULT_AUTHOR) -> Dict[str, str]:
    if template not in TEMPLATES:
        raise TemplateError(f"template must be one of {', '.join(TEMPLATES)}")
    if check.name_problem(name):
        raise TemplateError(check.name_problem(name))
    if dest.exists():
        raise TemplateError(f"{dest} already exists")
    body = "" if template == "minimal" else _TOOL.format(name=name) + _ROUTE
    files = {"carnivore.json": json.dumps(_manifest(name, template, author), indent=2) + "\n", f"{name}_main.py": _entry(name, body),
             "README.md": f"# {name}\n\nAuthored with `plugin new`. Edit `carnivore.json` (the one file you write), then `plugin check`, `plugin test`, `plugin link`.\n"}
    if template != "minimal":
        files[f"tests/test_{name}.py"] = _TEST.format(name=name)
    if template == "page":
        files["views/face/index.html"] = _VIEW.format(name=name)
    for rel, text in files.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(text, encoding="utf-8")
    return files
