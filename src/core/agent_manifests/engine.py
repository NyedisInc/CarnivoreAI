
from __future__ import annotations

import os
import re
import threading
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from ._pattern_safety import MAX_PATTERN_LEN, validate_pattern_ast

try:
    from re import _parser as _sre_parse  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    import sre_parse as _sre_parse  # type: ignore[no-redef]

logger = structlog.get_logger(__name__)

ENGINE_VERSION = 2
RULES_DIR = Path(__file__).with_name("rules")
MAX_LINES = 60
MAX_LINE_CHARS = 400
MAX_GATE_DEPTH = 16
MAX_RULES = 128
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


def compile_pattern(pattern: str, *, whole_region: bool = False) -> re.Pattern:
    if not isinstance(pattern, str):
        raise RuleFileError("pattern must be a string")
    if len(pattern) > MAX_PATTERN_LEN:
        raise RuleFileError(f"pattern exceeds {MAX_PATTERN_LEN} characters")
    try:
        parsed = _sre_parse.parse(pattern)
        validate_pattern_ast(parsed, pattern, whole_region=whole_region, error_cls=RuleFileError)
        return re.compile(pattern)
    except (re.error, RecursionError, OverflowError) as exc:
        raise RuleFileError("bad pattern %r: %s" % (pattern, exc)) from exc


def _str_seq(raw: Mapping[str, Any], key: str) -> Tuple[str, ...]:
    val = raw.get(key, ())
    if not isinstance(val, (list, tuple)) or not all(isinstance(s, str) for s in val):
        raise RuleFileError(f"{key} must be a list of strings")
    return tuple(val)


def _gate_seq(raw: Mapping[str, Any], key: str, depth: int) -> Tuple[Gate, ...]:
    val = raw.get(key, ())
    if not isinstance(val, (list, tuple)):
        raise RuleFileError(f"{key} must be a list of tables")
    return tuple(_gate(g, depth + 1) for g in val)


def _gate(raw: Mapping, depth: int = 0) -> Gate:
    if depth > MAX_GATE_DEPTH:
        raise RuleFileError(f"gate nesting exceeds {MAX_GATE_DEPTH}")
    if not isinstance(raw, Mapping):
        raise RuleFileError("gate must be a table")
    known = {"contains", "regex", "line_regex", "all", "any", "not"}
    extra = set(raw) - known - {"id", "state", "priority", "region", "visible_idle", "visible_blocker",
                                "visible_working", "skip_state_update"}
    if extra:
        raise RuleFileError("unknown keys %s" % sorted(extra))
    return Gate(
        contains=tuple(s.lower() for s in _str_seq(raw, "contains")),
        regex=tuple(compile_pattern(p, whole_region=True) for p in _str_seq(raw, "regex")),
        line_regex=tuple(compile_pattern(p, whole_region=False) for p in _str_seq(raw, "line_regex")),
        all=_gate_seq(raw, "all", depth),
        any=_gate_seq(raw, "any", depth),
        not_=_gate_seq(raw, "not", depth),
    )


def parse_manifest(text: str) -> Optional[Manifest]:
    if not isinstance(text, str):
        raise RuleFileError("manifest text must be a string")
    try:
        raw = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError) as exc:
        raise RuleFileError(str(exc)) from exc
    if not isinstance(raw, dict):
        raise RuleFileError("manifest must be a TOML table")
    min_ver = raw.get("min_engine_version", 1)
    if isinstance(min_ver, bool) or not isinstance(min_ver, int):
        raise RuleFileError("min_engine_version must be an integer")
    if min_ver > ENGINE_VERSION:
        return None
    manifest_id = raw.get("id")
    if not isinstance(manifest_id, str) or not manifest_id:
        raise RuleFileError("manifest id must be a non-empty string")
    version = raw.get("version", "")
    if not isinstance(version, str):
        raise RuleFileError("manifest version must be a string")
    aliases = _str_seq(raw, "aliases")
    raw_rules = raw.get("rules", [])
    if not isinstance(raw_rules, (list, tuple)) or len(raw_rules) > MAX_RULES:
        raise RuleFileError(f"rules must be a list of at most {MAX_RULES} items")
    rules = []
    for item in raw_rules:
        if not isinstance(item, Mapping):
            raise RuleFileError("each rule must be a table")
        rule_id = item.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise RuleFileError("rule id must be a non-empty string")
        state = item.get("state")
        if not isinstance(state, str) or state not in STATES:
            raise RuleFileError("rule %s: state %r" % (rule_id, state))
        raw_region = item.get("region", "whole_recent")
        if not isinstance(raw_region, str):
            raise RuleFileError("rule %s: region must be a string" % rule_id)
        region = raw_region.strip()
        if region != "whole_recent" and not _REGION_COUNT.match(region):
            raise RuleFileError("rule %s: region %r" % (rule_id, region))
        priority = item.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise RuleFileError("rule %s: priority must be an integer" % rule_id)
        skip = item.get("skip_state_update", False)
        if not isinstance(skip, bool):
            raise RuleFileError("rule %s: skip_state_update must be a boolean" % rule_id)
        if skip:
            continue
        rules.append(Rule(rule_id, state, priority, region, _gate(item)))
    names = (manifest_id,) + aliases
    return Manifest(manifest_id, version, names, tuple(rules))


_plugin_lock = threading.RLock()
_plugin_manifests: Dict[str, Tuple[Manifest, ...]] = {}


@lru_cache(maxsize=1)
def _builtin_manifests() -> Tuple[Manifest, ...]:
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


def register_plugin_manifests(plugin_id: str, items: Sequence[Manifest]) -> None:
    builtin_names = {name for m in _builtin_manifests() for name in m.names}
    with _plugin_lock:
        other_names = {
            name
            for pid, pitems in _plugin_manifests.items()
            if pid != plugin_id
            for m in pitems
            for name in m.names
        }
        taken = builtin_names | other_names
        for item in items:
            collision = sorted(set(item.names) & taken)
            if collision:
                raise RuleFileError(f"harness name(s) {collision} already registered")
            taken.update(item.names)
        _plugin_manifests[plugin_id] = tuple(items)


def unregister_plugin_manifests(plugin_id: str) -> None:
    with _plugin_lock:
        _plugin_manifests.pop(plugin_id, None)


def manifests() -> Tuple[Manifest, ...]:
    with _plugin_lock:
        plugin_items = tuple(m for items in _plugin_manifests.values() for m in items)
    return _builtin_manifests() + plugin_items


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
