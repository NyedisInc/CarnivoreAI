from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT = REPO_ROOT / "client"
WEB_SRC = REPO_ROOT / "web" / "src"
GUIDE_HTML = CLIENT / "style-guide.html"
GUIDE_DIR = CLIENT / "style-guide"
SECTIONS_DIR = GUIDE_DIR / "sections"
REGISTRY = GUIDE_DIR / "registry.json"
INDEX_HTML = CLIENT / "index.html"
TOKENS_CSS = WEB_SRC / "opscenter" / "tokens.css"

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STRING = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")
_ATTR = re.compile(r"\[[^\]]*\]")
_CLASS_IN_SELECTOR = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
_STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S)


def _selectors(css: str) -> list[str]:
    css = _STRING.sub('""', _COMMENT.sub("", css))
    out: list[str] = []
    buf: list[str] = []
    for ch in css:
        if ch == "{":
            sel = "".join(buf).split(";")[-1].strip()
            if sel and not sel.startswith("@"):
                out.append(sel)
            buf = []
        elif ch == "}":
            buf = []
        else:
            buf.append(ch)
    return out


def css_classes(css: str) -> set[str]:
    found: set[str] = set()
    for sel in _selectors(css):
        for match in _CLASS_IN_SELECTOR.finditer(_ATTR.sub("", sel)):
            found.add(match.group(1))
    return found


class PluginGuideError(ValueError):
    pass


PLUGIN_ROWS_NAME = "style-guide.json"
PLUGIN_PROSE_DIR = "style-guide"
PLUGINS_WEB = WEB_SRC / "cplugs"


def plugin_rows() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for path in sorted(PLUGINS_WEB.glob(f"*/{PLUGIN_ROWS_NAME}")):
        plugin = path.parent.name
        files = json.loads(path.read_text(encoding="utf-8")).get("files", {})
        outside = [k for k in files if not k.startswith(f"web/src/cplugs/{plugin}/")]
        if outside:
            raise PluginGuideError(f"{plugin}: style guide rows outside web/src/cplugs/{plugin}/: {outside}")
        found[plugin] = files
    return found


def load_registry() -> dict:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for plugin, files in plugin_rows().items():
        clash = sorted(set(files) & set(registry["files"]))
        if clash:
            raise PluginGuideError(f"{plugin}: rows also in registry.json: {clash}")
        registry["files"].update(files)
    return registry


def excluded(rel: str, registry: dict) -> bool:
    return any(rel.startswith(prefix) for prefix in registry.get("excluded", {}))


def shipped(registry: dict) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in sorted((CLIENT / "css").glob("*.css")):
        classes = css_classes(path.read_text(encoding="utf-8"))
        if classes:
            out[path.relative_to(REPO_ROOT).as_posix()] = classes
    for path in sorted(WEB_SRC.rglob("*.css")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        classes = css_classes(path.read_text(encoding="utf-8"))
        if classes and not excluded(rel, registry):
            out[rel] = classes
    for path in sorted(WEB_SRC.rglob("*.svelte")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if excluded(rel, registry):
            continue
        classes: set[str] = set()
        for block in _STYLE_BLOCK.findall(path.read_text(encoding="utf-8")):
            classes |= css_classes(block)
        out[rel] = classes
    return out


def registered(registry: dict) -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = {}
    for rel, entry in registry["files"].items():
        if "classes_by_section" in entry:
            out[rel] = {sec: set(cls) for sec, cls in entry["classes_by_section"].items()}
        else:
            out[rel] = {entry["section"]: set(entry.get("classes", []))}
    return out


def drift(registry: dict) -> tuple[dict[str, set[str]], dict[str, set[str]], list[str], list[str]]:
    code = shipped(registry)
    reg = registered(registry)
    missing: dict[str, set[str]] = {}
    stale: dict[str, set[str]] = {}
    for rel, classes in code.items():
        listed = set().union(*reg[rel].values()) if rel in reg else set()
        if rel not in reg:
            continue
        if classes - listed:
            missing[rel] = classes - listed
        if listed - classes:
            stale[rel] = listed - classes
    missing_files = sorted(set(code) - set(reg))
    stale_files = sorted(set(reg) - set(code))
    return missing, stale, missing_files, stale_files


def section_ids(registry: dict) -> list[str]:
    return [s["id"] for s in registry["sections"]]


def plugin_prose() -> dict[str, str]:
    return {f"{p.parent.parent.name}/{p.name}": p.read_text(encoding="utf-8")
            for p in sorted(PLUGINS_WEB.glob(f"*/{PLUGIN_PROSE_DIR}/*.html"))}


def fragment_text() -> dict[str, str]:
    found = {p.name: p.read_text(encoding="utf-8") for p in sorted(SECTIONS_DIR.glob("*.html"))}
    found.update(plugin_prose())
    return found


def all_defined_classes() -> set[str]:
    found: set[str] = set()
    for path in list((CLIENT / "css").rglob("*.css")) + list(WEB_SRC.rglob("*.css")):
        found |= css_classes(path.read_text(encoding="utf-8"))
    for path in WEB_SRC.rglob("*.svelte"):
        for block in _STYLE_BLOCK.findall(path.read_text(encoding="utf-8")):
            found |= css_classes(block)
    return found


def source_text() -> str:
    parts = []
    for path in (CLIENT / "js").rglob("*.js"):
        parts.append(path.read_text(encoding="utf-8"))
    for pattern in ("*.svelte", "*.ts"):
        for path in WEB_SRC.rglob(pattern):
            if "style-guide" in path.parts:
                continue
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def oc_tokens() -> set[str]:
    text = _COMMENT.sub("", TOKENS_CSS.read_text(encoding="utf-8"))
    return set(re.findall(r"(--oc-[\w-]+)\s*:", text))


def stylesheet_links(html: str) -> list[str]:
    return re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)


def _print_gap() -> int:
    registry = load_registry()
    missing, stale, missing_files, stale_files = drift(registry)
    for rel in missing_files:
        print(f"UNREGISTERED FILE  {rel}")
    for rel, classes in sorted(missing.items()):
        print(f"UNREGISTERED CLASS {rel}: {' '.join(sorted(classes))}")
    for rel in stale_files:
        print(f"GONE FILE          {rel}")
    for rel, classes in sorted(stale.items()):
        print(f"GONE CLASS         {rel}: {' '.join(sorted(classes))}")
    return 1 if (missing or stale or missing_files or stale_files) else 0


if __name__ == "__main__":
    sys.exit(_print_gap())
