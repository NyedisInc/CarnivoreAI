
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterator, List

from src.models.mods import ModApiCalls, ModGatingHook, ModHookEvents, ModReport

_HOOKS = re.compile(r"^(\S+) hooks: (.+)$")
_CALLS = re.compile(r"^(\S+) calls: (.+)$")


def _sections(raw: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    manifest = raw.get("manifest")
    if isinstance(manifest, dict):
        yield manifest
    contents = raw.get("contents")
    for block in contents if isinstance(contents, list) else []:
        if isinstance(block, dict):
            yield block


def _strings(value: Any) -> List[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def parse_report(raw: Any, claude_version: str) -> ModReport:
    report = ModReport(claude_version=claude_version)
    if not isinstance(raw, dict):
        return report
    for block in _sections(raw):
        report.warnings += _strings(block.get("warnings"))
        for note in _strings(block.get("notes")):
            hooks, calls = _HOOKS.match(note), _CALLS.match(note)
            if hooks:
                report.hooks.append(ModHookEvents(module=hooks.group(1), events=_split(hooks.group(2))))
            elif calls:
                report.calls.append(ModApiCalls(module=calls.group(1), calls=_split(calls.group(2))))
            else:
                report.notes_raw.append(note)
        for gate in block.get("gatingHooks") if isinstance(block.get("gatingHooks"), list) else []:
            if isinstance(gate, dict):
                report.gating.append(ModGatingHook(
                    module=str(gate.get("module", "")), pattern=str(gate.get("pattern", "")),
                    hook=str(gate.get("hook", "")), has_catch=gate.get("hasCatch") is True))
    report.spends_plan_usage = any(c.startswith("$.model.") for entry in report.calls for c in entry.calls)
    return report


def _split(text: str) -> List[str]:
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += (ch == "{") - (ch == "}")
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return [item for item in out if item]


def report_sha(report: ModReport) -> str:
    canon = json.dumps(report.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
