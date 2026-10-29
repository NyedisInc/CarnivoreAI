from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[3]

SERVER_MODULES = (
    "src/cplugs/host/install_gates.py",
    "src/core/catalog/publish_prepare_kinds.py",
    "src/api/catalog_install_support.py",
    "src/api/catalog_installed_support.py",
    "hosted/catalog/api/validate_kinds.py",
    "hosted/catalog/api/validate_cplug.py",
)
FEATURE_USER_FIELDS = ("name", "summary", "description", "where", "how_to", "examples")
FILES = ("hosted/catalog_index/seed_readme.md", "docs/extension-contract.md")

BAD = re.compile(r"\b(?:(?:a|the|this|that|each)\s+cplugs?|sidecar\s+plugins?|claude\s+code\s+plugins?)\b", re.IGNORECASE)
API_PATH = re.compile(r"/api/v1/\S*")
ALLOWED = ("a mod is a claude code plugin",)


def offences(text: str) -> List[str]:
    text = API_PATH.sub("", text)
    for phrase in ALLOWED:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    return [m.group(0) for m in BAD.finditer(text)]


def _docstring_nodes(tree: ast.AST) -> set:
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                skip.add(id(first.value))
    return skip


def module_literals(path: Path) -> Iterable[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.value


def cplugs_doc_section_7() -> str:
    text = (ROOT / "docs/cplugs.md").read_text(encoding="utf-8")
    start = re.search(r"^## 7\. ", text, re.MULTILINE)
    assert start, "docs/cplugs.md lost its section 7"
    rest = text[start.start():]
    nxt = re.search(r"^## (?!7\.)", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def test_the_matcher_can_go_red() -> None:
    assert offences("a cplug may not link") == ["a cplug"]
    assert offences("each Cplugs") == ["each Cplugs"]
    assert offences("a sidecar plugin") == ["sidecar plugin"]
    assert offences("the Claude Code plugin") == ["Claude Code plugin"]
    assert offences("GET /api/v1/cplugs/x and cplug.json and the plugin") == []


def test_server_messages_say_plugin() -> None:
    found = {m: [o for s in module_literals(ROOT / m) for o in offences(s)] for m in SERVER_MODULES}
    assert {m: o for m, o in found.items() if o} == {}


def test_feature_catalog_user_fields_say_plugin() -> None:
    bad = {}
    for path in sorted((ROOT / "features/catalog").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps([doc.get(k) for k in FEATURE_USER_FIELDS], ensure_ascii=False)
        if offences(text):
            bad[path.name] = offences(text)
    assert bad == {}


def test_author_material_says_plugin() -> None:
    bad = {f: offences((ROOT / f).read_text(encoding="utf-8")) for f in FILES}
    bad["docs/cplugs.md section 7"] = offences(cplugs_doc_section_7())
    assert {k: v for k, v in bad.items() if v} == {}
