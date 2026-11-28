
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from scripts.plugin import check

TEMPLATES = ("minimal", "sidecar", "page")
FIELD_FLOOR = "1.16.2"
PAGE_TOPICS_FLOOR = "1.16.6"
_DEFAULT_AUTHOR = "me"


class TemplateError(ValueError):
    pass


def _entry(name: str, body: str) -> str:
    return (
        f'"""The {name} entry: handlers the host calls over its sandboxed pipe."""\n\n'
        "from __future__ import annotations\n\n"
        "import asyncio\n"
        "from typing import Any, Dict\n\n"
        "from cplug_sdk import Plugin\n\n"
        "plugin = Plugin()\n"
        f"{body}"
        '\nif __name__ == "__main__":\n'
        "    asyncio.run(plugin.serve())\n"
    )


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


def _manifest(name: str, template: str, author: str) -> str:
    min_ver = PAGE_TOPICS_FLOOR if template == "page" else FIELD_FLOOR
    lines = [
        "schema = 2",
        f"id = {json.dumps(name)}",
        f"name = {json.dumps(name)}",
        'version = "0.1.0"',
        'kind = "plugin"',
        f"description = {json.dumps(f'The {name} plugin.')}",
        f"author = {json.dumps(author)}",
        'license = "MIT"',
        "api_version = 1",
        f"min_app_version = {json.dumps(min_ver)}",
        "",
        "[run]",
        f'cmd = ["python3", "{name}_main.py"]',
        'mode = "rpc"',
    ]
    if template != "minimal":
        lines.extend([
            "",
            "[ui]",
            'routes = ["status"]',
        ])
        if template == "page":
            lines.extend([
                'topics = ["changed"]',
                "",
                "[ui.page]",
                'menu = "face"',
                'main = "face"',
                "",
                "[[ui.views]]",
                'name = "face"',
                'surfaces = ["panel"]',
                'files = ["index.html"]',
            ])
        lines.extend([
            "",
            "[[mcp.tools]]",
            f'name = "{name}_hello"',
            'description = "Says hello. Reads nothing and changes nothing."',
            'gate = "read"',
            'inputSchema = { type = "object", properties = {}, additionalProperties = false }',
        ])
    return "\n".join(lines) + "\n"


def scaffold(dest: Path, name: str, template: str, author: str = _DEFAULT_AUTHOR) -> Dict[str, str]:
    if template not in TEMPLATES:
        raise TemplateError(f"template must be one of {', '.join(TEMPLATES)}")
    if check.name_problem(name):
        raise TemplateError(check.name_problem(name))
    if dest.exists():
        raise TemplateError(f"{dest} already exists")
    body = "" if template == "minimal" else _TOOL.format(name=name) + _ROUTE
    files = {
        "carnivore.toml": _manifest(name, template, author),
        f"{name}_main.py": _entry(name, body),
        "README.md": f"# {name}\n\nAuthored with `plugin new`. Edit `carnivore.toml`, then `plugin check`, `plugin test`, `plugin link`.\n",
    }
    if template != "minimal":
        files[f"tests/test_{name}.py"] = _TEST.format(name=name)
    if template == "page":
        files["views/face/index.html"] = _VIEW.format(name=name)
    for rel, text in files.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(text, encoding="utf-8")
    return files
