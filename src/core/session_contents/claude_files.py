
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.core.session_contents import constants as C
from src.core.session_contents.entries import Item, item, read_json, real_key

logger = structlog.get_logger()

_IMPORT_RX = re.compile(r"(?<![\w`@])@((?:~|\.{1,2})?/?[\w.\-/~]+\.\w+)")
_FENCE_RX = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
SETTINGS_NAMES = ("settings.json", "settings.local.json")


def managed_dirs() -> List[Path]:
    return [Path(p) for p in C.CLAUDE_MANAGED_DIRS if Path(p).is_dir()]


def same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def project_claude_dirs(chain: List[Path], config_dir: Path) -> List[Path]:
    return [d / ".claude" for d in chain if (d / ".claude").is_dir() and not same_dir(d / ".claude", config_dir)]


def _imports_of(path: Path) -> List[Path]:
    try:
        if path.stat().st_size > C.MAX_READ_BYTES:
            return []
        text = _FENCE_RX.sub("", path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []
    found: List[Path] = []
    for raw in _IMPORT_RX.findall(text):
        target = Path(raw).expanduser()
        target = target if target.is_absolute() else path.parent / target
        if target.is_file():
            found.append(target)
    return found


def _instruction(path: Path, scope: str, via: str = "") -> Item:
    detail = f"imported by {via}" if via else ""
    return item(path.name if path.parent.name != "rules" else f"rules/{path.name}", scope, path, detail=detail)


def instruction_items(config_dir: Path, chain: List[Path]) -> List[Item]:
    roots: List[Tuple[Path, str]] = []
    for managed in managed_dirs():
        roots.append((managed / "CLAUDE.md", C.SCOPE_GLOBAL))
    roots.append((config_dir / "CLAUDE.md", C.SCOPE_GLOBAL))
    roots += [(p, C.SCOPE_GLOBAL) for p in sorted((config_dir / "rules").rglob("*.md"))]
    for folder in chain:
        roots += [(folder / "CLAUDE.md", C.SCOPE_PROJECT), (folder / ".claude" / "CLAUDE.md", C.SCOPE_PROJECT),
                  (folder / "CLAUDE.local.md", C.SCOPE_PROJECT)]
        if not same_dir(folder / ".claude", config_dir):
            roots += [(p, C.SCOPE_PROJECT) for p in sorted((folder / ".claude" / "rules").rglob("*.md"))]
    out: List[Item] = []
    seen: Set[Path] = set()

    def walk(path: Path, scope: str, depth: int, via: str) -> None:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            return
        seen.add(resolved)
        out.append(_instruction(path, scope, via))
        if depth < C.MAX_IMPORT_DEPTH:
            for target in _imports_of(path):
                walk(target, scope, depth + 1, path.name)

    for path, scope in roots:
        walk(path, scope, 0, "")
    return out


def settings_layers(config_dir: Path, claude_dirs: List[Path]) -> List[Tuple[Path, str, Dict[str, Any]]]:
    layers: List[Tuple[Path, str, Dict[str, Any]]] = []
    candidates = [(config_dir / "settings.json", C.SCOPE_GLOBAL)]
    for folder in claude_dirs:
        candidates += [(folder / name, C.SCOPE_PROJECT) for name in SETTINGS_NAMES]
    candidates += [(m / "managed-settings.json", C.SCOPE_GLOBAL) for m in managed_dirs()]
    seen: Set[Optional[str]] = set()
    for path, scope in candidates:
        if path.is_file() and real_key(path) not in seen:
            seen.add(real_key(path))
            layers.append((path, scope, read_json(path)))
    return layers


def enabled_plugins(layers: List[Tuple[Path, str, Dict[str, Any]]]) -> Dict[str, bool]:
    merged: Dict[str, bool] = {}
    for _, _, doc in layers:
        table = doc.get("enabledPlugins")
        if isinstance(table, dict):
            merged.update({str(k): v is True for k, v in table.items()})
    return merged


def installed_plugins(config_dir: Path) -> List[Tuple[str, Path, str]]:
    table = read_json(config_dir / "plugins" / "installed_plugins.json").get("plugins")
    out: List[Tuple[str, Path, str]] = []
    if not isinstance(table, dict):
        return out
    for key, value in table.items():
        for entry in value if isinstance(value, list) else [value]:
            if isinstance(entry, dict) and isinstance(entry.get("installPath"), str):
                out.append((str(key), Path(entry["installPath"]), str(entry.get("version") or "")))
    return out


def plugin_label(key: str) -> str:
    return key.split("@", 1)[0]


def hook_items(layers: List[Tuple[Path, str, Dict[str, Any]]], plugin_roots: List[Tuple[str, Path, bool]]) -> List[Item]:
    out: List[Item] = []
    sources: List[Tuple[Path, str, Dict[str, Any], str]] = [(p, s, d, "") for p, s, d in layers]
    for name, root, enabled in plugin_roots:
        path = root / "hooks" / "hooks.json"
        if path.is_file():
            sources.append((path, C.SCOPE_PLUGIN, read_json(path), f"plugin {name}" + ("" if enabled else " (disabled)")))
    for path, scope, doc, origin in sources:
        table = doc.get("hooks")
        if not isinstance(table, dict):
            continue
        for event, groups in table.items():
            for group in groups if isinstance(groups, list) else []:
                if not isinstance(group, dict):
                    continue
                matcher = group.get("matcher")
                label = f"{event} [{matcher}]" if isinstance(matcher, str) and matcher else str(event)
                for hook in group.get("hooks") or []:
                    out.append(item(label, scope, path, detail=_hook_detail(hook, origin)))
    return out


def executable_name(command: Any) -> str:
    if not isinstance(command, str):
        return ""
    for token in command.split():
        if "=" not in token:
            return Path(token.strip("\"'")).name
    return ""


def _hook_detail(hook: Any, origin: str) -> str:
    if not isinstance(hook, dict):
        return origin
    kind = str(hook.get("type") or "command")
    command = hook.get("command")
    exe = executable_name(command) if kind == "command" else ""
    return " ".join(p for p in (kind, exe, f"({origin})" if origin else "") if p)
