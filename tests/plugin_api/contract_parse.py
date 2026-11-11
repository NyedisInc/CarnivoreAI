
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

STABILITY = frozenset({"stable", "experimental"})
STABILITY_COLUMN = "Stability"
NONE_CELL = "-"
_CONVERTER = re.compile(r"\{(\w+):\w+\}")
_HEADING = re.compile(r"^(#{2,3}) (\d+(?:\.\d+)?)\b(.*)$")
_TICKED = re.compile(r"`([^`]+)`")


@dataclass
class Table:

    section: str
    header: List[str]
    rows: List[Dict[str, str]] = field(default_factory=list)


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tables(text: str) -> List[Table]:
    found: List[Table] = []
    section = ""
    current: Optional[Table] = None
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            section, current = heading.group(2), None
            continue
        if not line.startswith("|"):
            current = None
            continue
        if current is None:
            current = Table(section, _cells(line))
            found.append(current)
        elif not set(line.replace("|", "").strip()) <= set("-: "):
            current.rows.append(dict(zip(current.header, _cells(line))))
    return found


def contract_tables(text: str, section: str) -> List[Table]:
    return [t for t in tables(text) if STABILITY_COLUMN in t.header and (t.section == section or t.section.startswith(section + "."))]


def contract_rows(text: str, section: str) -> List[Dict[str, str]]:
    return [row for t in contract_tables(text, section) for row in t.rows]


def ticked(cell: str) -> List[str]:
    return _TICKED.findall(cell)


def first_ticked(cell: str) -> str:
    items = ticked(cell)
    return items[0] if items else cell


def bare_path(path: str) -> str:
    return _CONVERTER.sub(r"{\1}", path)




def render_params(func: Callable[..., Any], drop_first: bool = False) -> str:
    params = list(inspect.signature(func).parameters.values())
    if drop_first:
        params = params[1:]
    out: List[str] = []
    star_written = False
    for p in params:
        if p.kind is p.VAR_POSITIONAL:
            out.append(f"*{p.name}")
            star_written = True
            continue
        if p.kind is p.VAR_KEYWORD:
            out.append(f"**{p.name}")
            continue
        if p.kind is p.KEYWORD_ONLY and not star_written:
            out.append("*")
            star_written = True
        out.append(p.name if p.default is p.empty else f"{p.name}={p.default!r}")
    return ", ".join(out)


def public_members(cls: type) -> Dict[str, Any]:
    return {n: v for n, v in vars(cls).items() if not n.startswith("_")}


def public_instance_attrs(obj: Any) -> Set[str]:
    return {n for n in vars(obj) if not n.startswith("_")}


def member_kind(raw: Any) -> str:
    if isinstance(raw, property):
        return "property"
    if inspect.isfunction(raw):
        return "method"
    return "attribute"


def module_kind(value: Any) -> str:
    if inspect.isclass(value):
        return "exception" if issubclass(value, BaseException) else "class"
    if inspect.isfunction(value) or inspect.isbuiltin(value):
        return "function"
    return "constant"



_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)
_EXPORT_LIST = re.compile(r"\bexport\s+(?:type\s+)?\{([^}]*)\}")
_EXPORT_DECL = re.compile(r"\bexport\s+(?:declare\s+)?(?:default\s+)?(?:async\s+)?(?:abstract\s+)?"
                          r"(?:function\*?|const|let|var|class|interface|type|enum)\s+(\w+)")
_EXPORT_STAR = re.compile(r"\bexport\s+\*")


class UnreadableExport(ValueError):
    pass


def ts_exports(path: Path) -> Set[str]:
    source = _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", path.read_text()))
    if _EXPORT_STAR.search(source):
        raise UnreadableExport(f"{path} re-exports with export *; list the names")
    names: Set[str] = set(_EXPORT_DECL.findall(source))
    for block in _EXPORT_LIST.findall(source):
        for item in block.split(","):
            item = re.sub(r"^\s*type\s+", "", item).strip()
            if item:
                names.add(item.split(" as ")[-1].strip())
    return names


def sdk_modules(folder: Path) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {}
    for path in sorted(folder.glob("*.ts")):
        if path.name.endswith(".test.ts"):
            continue
        names = ts_exports(path)
        if names:
            out[path.name] = names
    return out




def route_inputs(route: Any) -> str:
    parts = [f"?{p.name}" for p in route.dependant.query_params]
    for body in route.dependant.body_params:
        fields = getattr(body.field_info.annotation, "model_fields", None)
        parts.append("{" + ", ".join(sorted(fields)) + "}" if fields else f"{{{body.name}}}")
    return " ".join(parts) if parts else NONE_CELL


def route_cite(route: Any, repo: Path) -> str:
    func = inspect.unwrap(route.endpoint)
    return f"{Path(inspect.getsourcefile(func)).resolve().relative_to(repo)}::{func.__name__}"


def doc_verbs(cell: str) -> Tuple[str, ...]:
    return tuple(sorted(v.strip() for v in cell.split(",") if v.strip()))

