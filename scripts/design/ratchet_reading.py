
from __future__ import annotations

import json
import re

BASELINE_JSON = "tests/fixtures/design_raw_values_baseline.json"
CONTROLS_JSON = "tests/fixtures/design_raw_controls_baseline.json"
LEGACY_JSON = "tests/fixtures/design_legacy_known.json"
UNCOVERED_JSON = "web/src/lib/i18n/uncovered-known.json"
BASELINES = {BASELINE_JSON: "baseline", CONTROLS_JSON: "controls", LEGACY_JSON: "legacy", UNCOVERED_JSON: "uncovered"}

_CEILING = re.compile(r"^(?:export\s+)?(?:const\s+)?([A-Z][A-Z0-9_]*)\s*(?::\s*[\w\[\], ]+)?\s*=\s*(\d[\d_]*)\s*;?\s*(?:#.*|//.*)?$", re.M)
_LIST_HEAD = re.compile(r"^(?:export\s+)?(?:const\s+)?([A-Z][A-Z0-9_]*)\s*(?::[^=\n]*)?=\s*(?:new\s+Set\(\s*|frozenset\(\s*|set\(\s*)?([\[{(])", re.M)
_CLOSE = {"[": "]", "{": "}", "(": ")"}


class GuardError(Exception):
    pass


def is_ceiling_name(name: str) -> bool:
    return name.endswith("CEILING") or name.endswith("BASELINE") or name.startswith("MAX_")


def is_list_name(name: str) -> bool:
    return "KNOWN" in name or "ALLOW" in name


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*(?://|#).*$", "", text)


def _top_level_entries(body: str) -> int:
    depth, count, i, quote = 0, 0, 0, ""
    is_dict = body[:1] == "{"
    want_key, keyed = True, False
    while i < len(body):
        ch = body[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
            if depth == 1 and (want_key or not is_dict):
                count += 1
                keyed = True
        elif ch in "[{(":
            depth += 1
            if depth == 2 and ch == "{" and not is_dict:
                count += 1
        elif ch in "]})":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1 and is_dict and ch == ":":
            count += 0 if keyed or not want_key else 1
            want_key = False
        elif depth == 1 and ch == ",":
            want_key, keyed = True, False
        i += 1
    return count


def ratchets_in_source(path: str, text: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for match in _CEILING.finditer(text):
        if is_ceiling_name(match.group(1)):
            found[f"{path}:{match.group(1)}"] = int(match.group(2).replace("_", ""))
    for match in _LIST_HEAD.finditer(text):
        name = match.group(1)
        if not is_list_name(name):
            continue
        body = _strip_comments(text[match.start(2):])
        found[f"{path}:{name}#entries"] = _top_level_entries(body)
    return found


def ratchets_in_baseline(text: str, prefix: str = "baseline") -> dict[str, int]:
    try:
        files = json.loads(text).get("files", {})
    except (ValueError, AttributeError) as exc:
        raise GuardError(f"a baseline is not readable JSON: {exc}") from exc
    return {f"{prefix}:{name}:{kind}": int(n) for name, kinds in files.items() for kind, n in kinds.items()}


def ratchets_in_known(path: str, text: str) -> dict[str, int]:
    prefix = BASELINES[path]
    try:
        doc = json.loads(text)
        if path == UNCOVERED_JSON:
            return {f"{prefix}:{name}": int(n) for name, n in doc.items()}
        rows: dict[str, int] = {}
        for section, files in doc.get("sections", {}).items():
            for name, value in files.items():
                if isinstance(value, dict):
                    rows.update({f"{prefix}:{section}:{name}:{kind}": int(n) for kind, n in value.items()})
                else:
                    rows[f"{prefix}:{section}:{name}"] = int(value)
        return rows
    except (ValueError, AttributeError, TypeError) as exc:
        raise GuardError(f"{path} is not a readable known list: {exc}") from exc
