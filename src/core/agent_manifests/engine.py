
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

import structlog

try:
    from re import _parser as _sre_parse  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    import sre_parse as _sre_parse  # type: ignore[no-redef]

logger = structlog.get_logger(__name__)

ENGINE_VERSION = 2
RULES_DIR = Path(__file__).with_name("rules")
MAX_LINES = 60
MAX_LINE_CHARS = 400
STATES = ("working", "blocked", "idle")
RUNTIMES = frozenset({"node", "bun", "deno", "python", "python3"})
_REGION_COUNT = re.compile(r"^(bottom_non_empty_lines|bottom_lines)\((\d{1,3})\)$")


class RuleFileError(ValueError):
    pass


@dataclass(frozen=True)
class Gate:

    contains: Tuple[str, ...] = ()
    regex: Tuple[re.Pattern, ...] = ()
    line_regex: Tuple[re.Pattern, ...] = ()
    all: Tuple["Gate", ...] = ()
    any: Tuple["Gate", ...] = ()
    not_: Tuple["Gate", ...] = ()


@dataclass(frozen=True)
class Rule:

    id: str
    state: str
    priority: int
    region: str
    gate: Gate


@dataclass(frozen=True)
class Manifest:

    id: str
    version: str
    names: Tuple[str, ...]
    rules: Tuple[Rule, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Match:

    cli: str
    state: str
    rule: str
    version: str


def _nested_quantifier(items: Iterable, inside: bool = False) -> bool:
    for op, av in items:
        name = str(op)
        if name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
            if inside:
                return True
            if _nested_quantifier(av[2], av[1] > 1):
                return True
        elif name == "SUBPATTERN":
            if _nested_quantifier(av[-1], inside):
                return True
        elif name == "BRANCH":
            if any(_nested_quantifier(b, inside) for b in av[1]):
                return True
        elif name in ("ASSERT", "ASSERT_NOT"):
            if _nested_quantifier(av[1], inside):
                return True
    return False


def compile_pattern(pattern: str) -> re.Pattern:
    try:
        if _nested_quantifier(_sre_parse.parse(pattern)):
            raise RuleFileError("nested quantifier in %r" % pattern)
        return re.compile(pattern)
    except re.error as exc:
        raise RuleFileError("bad pattern %r: %s" % (pattern, exc)) from exc


def _gate(raw: Mapping) -> Gate:
    known = {"contains", "regex", "line_regex", "all", "any", "not"}
    extra = set(raw) - known - {"id", "state", "priority", "region", "visible_idle", "visible_blocker",
                                "visible_working", "skip_state_update"}
    if extra:
        raise RuleFileError("unknown keys %s" % sorted(extra))
    return Gate(
        contains=tuple(str(s).lower() for s in raw.get("contains", ())),
        regex=tuple(compile_pattern(p) for p in raw.get("regex", ())),
        line_regex=tuple(compile_pattern(p) for p in raw.get("line_regex", ())),
        all=tuple(_gate(g) for g in raw.get("all", ())),
        any=tuple(_gate(g) for g in raw.get("any", ())),
        not_=tuple(_gate(g) for g in raw.get("not", ())),
    )


def parse_manifest(text: str) -> Optional[Manifest]:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RuleFileError(str(exc)) from exc
    if int(raw.get("min_engine_version", 1)) > ENGINE_VERSION:
        return None
    rules = []
    for item in raw.get("rules", ()):
        state, region = item.get("state"), str(item.get("region", "whole_recent")).strip()
        if state not in STATES:
            raise RuleFileError("rule %s: state %r" % (item.get("id"), state))
        if region != "whole_recent" and not _REGION_COUNT.match(region):
            raise RuleFileError("rule %s: region %r" % (item.get("id"), region))
        if item.get("skip_state_update"):
            continue
        rules.append(Rule(str(item["id"]), state, int(item.get("priority", 0)), region, _gate(item)))
    names = (str(raw["id"]),) + tuple(str(a) for a in raw.get("aliases", ()))
    return Manifest(str(raw["id"]), str(raw.get("version", "")), names, tuple(rules))


@lru_cache(maxsize=1)
def manifests() -> Tuple[Manifest, ...]:
    out: List[Manifest] = []
    for path in sorted(RULES_DIR.glob("*.toml")):
        try:
            manifest = parse_manifest(path.read_text(encoding="utf-8"))
        except (OSError, RuleFileError, KeyError, ValueError) as exc:
            logger.warning("agent_manifest_skipped", file=path.name, error=str(exc))
            continue
        if manifest is None:
            logger.info("agent_manifest_needs_newer_engine", file=path.name)
            continue
        out.append(manifest)
    return tuple(out)


def _by_name() -> Dict[str, Manifest]:
    return {name: m for m in manifests() for name in m.names}


def cli_name(command: str) -> Optional[str]:
    parts = command.split()
    if not parts:
        return None
    first = os.path.basename(parts[0]).lower()
    if first in RUNTIMES:
        script = next((p for p in parts[1:] if not p.startswith("-")), None)
        return os.path.basename(script).lower() if script else None
    return first


def identify(pane_pid: Optional[int], parents: Mapping[int, int], commands: Mapping[int, str],
             max_depth: int = 6) -> Optional[Manifest]:
    if pane_pid is None:
        return None
    table = _by_name()
    best: Optional[Tuple[int, Manifest]] = None
    for pid, command in commands.items():
        manifest = table.get(cli_name(command) or "")
        if manifest is None:
            continue
        depth, cur = 0, pid
        while cur != pane_pid and depth < max_depth:
            cur = parents.get(cur, 0)
            depth += 1
            if cur <= 1:
                break
        if cur == pane_pid and (best is None or depth < best[0]):
            best = (depth, manifest)
    return best[1] if best else None


def _cap(text: str) -> List[str]:
    lines = [line[:MAX_LINE_CHARS] for line in text.splitlines()[-MAX_LINES:]]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _region(lines: List[str], spec: str) -> List[str]:
    m = _REGION_COUNT.match(spec)
    if not m:
        return lines
    count = int(m.group(2))
    if m.group(1) == "bottom_lines":
        return lines[-count:] if count else []
    idx = [i for i, line in enumerate(lines) if line.strip()]
    return lines[idx[-min(count, len(idx))]:] if count and idx else []


def _holds(gate: Gate, text: str, lower: str, lines: List[str]) -> bool:
    if not all(needle in lower for needle in gate.contains):
        return False
    if not all(p.search(text) for p in gate.regex):
        return False
    if not all(any(p.search(line) for line in lines) for p in gate.line_regex):
        return False
    if not all(_holds(g, text, lower, lines) for g in gate.all):
        return False
    if gate.any and not any(_holds(g, text, lower, lines) for g in gate.any):
        return False
    return not any(_holds(g, text, lower, lines) for g in gate.not_)


def evaluate(manifest: Manifest, screen: str) -> Optional[Match]:
    lines = _cap(screen)
    best: Optional[Rule] = None
    for rule in manifest.rules:
        if best is not None and rule.priority <= best.priority:
            continue
        region = _region(lines, rule.region)
        text = "\n".join(region)
        if _holds(rule.gate, text, text.lower(), region):
            best = rule
    if best is None:
        return None
    return Match(manifest.id, best.state, best.id, manifest.version)
