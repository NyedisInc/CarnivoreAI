
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

_LINE = re.compile(
    r"""^\s*'(?P<key>[a-z0-9_.]+)':\s*(?:'(?P<single>(?:[^'\\]|\\.)*)'|"(?P<double>(?:[^"\\]|\\.)*)"),\s*$"""
)
_ESCAPE = re.compile(r"\\(.)")

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[3] / "client" / "js" / "i18n" / "catalog.en.js"
PLUGINS_ROOT = Path(__file__).resolve().parents[2] / "cplugs"
PLUGIN_SLICE_NAME = "notify.catalog.en.js"


def read_prefixed(prefixes: Iterable[str], path: Path = DEFAULT_CATALOG_PATH) -> Dict[str, str]:
    wanted: Tuple[str, ...] = tuple(f"'{p}" for p in prefixes)
    found: Dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.lstrip().startswith(wanted):
                continue
            match = _LINE.match(line)
            if not match:
                raise ValueError(f"{path}:{number}: unparseable catalog line under a requested prefix")
            raw = match.group("single") if match.group("single") is not None else match.group("double")
            found[match.group("key")] = _ESCAPE.sub(r"\1", raw)
    return found


def plugin_slice_paths(root: Path = PLUGINS_ROOT) -> List[Path]:
    return sorted(p for p in root.glob(f"*/{PLUGIN_SLICE_NAME}") if (p.parent / "cplug.json").is_file())


def read_plugin_slices(suffixes: Iterable[str], root: Path = PLUGINS_ROOT) -> Dict[str, str]:
    tails = tuple(suffixes)
    found: Dict[str, str] = {}
    for path in plugin_slice_paths(root):
        namespace = f"cplug.{path.parent.name}."
        everything = read_prefixed(("cplug.",), path)
        stray = [k for k in everything if not k.startswith(namespace)]
        if stray:
            raise ValueError(f"{path}: key outside {namespace}: {stray[0]}")
        found.update({k: v for k, v in everything.items() if k.startswith(tuple(namespace + t for t in tails))})
    return found
