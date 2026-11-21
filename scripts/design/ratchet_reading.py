
from __future__ import annotations

import ast
import json
import re

BASELINE_JSON = "tests/fixtures/design_raw_values_baseline.json"
CONTROLS_JSON = "tests/fixtures/design_raw_controls_baseline.json"
LEGACY_JSON = "tests/fixtures/design_legacy_known.json"
UNCOVERED_JSON = "web/src/lib/i18n/uncovered-known.json"
INFINITE_JSON = "tests/fixtures/infinite_animations_baseline.json"
CONTRAST_JSON = "tests/fixtures/design_contrast_roles_baseline.json"
REACH_JSON = "tests/fixtures/design_reach_ins_baseline.json"
THIN_JSON = "tests/fixtures/error_log_thin_baseline.json"
BASELINES = {
    THIN_JSON: "thin", BASELINE_JSON: "baseline", CONTROLS_JSON: "controls", LEGACY_JSON: "legacy", UNCOVERED_JSON: "uncovered",
    INFINITE_JSON: "infinite", CONTRAST_JSON: "contrast", REACH_JSON: "reach",
}
KNOWN_SHAPED = frozenset({LEGACY_JSON, UNCOVERED_JSON, THIN_JSON, INFINITE_JSON, CONTRAST_JSON})
EXTRA_LISTS: dict[str, tuple[str, ...]] = {
    "scripts/design/harness_paths.py": ("HARNESS_DIRS", "HARNESS_FILES"),
    "scripts/design/raw_values.py": ("EXEMPT",),
    "web/src/lib/zone-shell/host-scan.ts": ("DIALOG_OPT_OUT",),
    "tests/python/domain_ops/test_bare_raise_ratchet.py": ("BARE_RAISE_KNOWN",),
    "tests/python/domain_ops/test_request_shim_ratchet.py": ("REQUEST_SHIM_KNOWN",),
}
ROW_KEY = re.compile(r"^(?P<head>[^:]+:[A-Z][A-Z0-9_]*)\[(?P<row>.*)\]$", re.S)
_INT_ROW = re.compile(r"""(['"])((?:(?!\1).)*)\1\s*:\s*(\d[\d_]*)\s*(?:,|$)""")

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


def _bracket_body(body: str) -> str:
    depth, quote, i = 0, "", 0
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
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
            if depth == 0:
                return body[1:i]
        i += 1
    return ""


def int_rows(body: str) -> dict[str, int] | None:
    if body[:1] != "{":
        return None
    inner = _bracket_body(body).strip()
    if not inner or re.search(r"[\[{(]", re.sub(r"(['\"]).*?\1", "", inner)):
        return None
    rows = {m.group(2): int(m.group(3).replace("_", "")) for m in _INT_ROW.finditer(inner)}
    return rows if rows and len(rows) == _top_level_entries(body) else None


def _py_allowances(path: str, text: str) -> dict[str, dict[str, int]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise GuardError(f"{path} does not parse: {exc}") from exc
    found: dict[str, dict[str, int]] = {}
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else getattr(node, "target", None)
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(target, ast.Name) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", target.id) or not isinstance(value, ast.Dict):
            continue
        keys, vals = value.keys, value.values
        if keys and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in keys) and all(
            isinstance(v, ast.Constant) and type(v.value) is int for v in vals
        ):
            found[target.id] = {k.value: v.value for k, v in zip(keys, vals)}  # type: ignore[union-attr]
    return found


def ratchets_in_source(path: str, text: str, extra: tuple[str, ...] = ()) -> dict[str, int]:
    found: dict[str, int] = {}
    for match in _CEILING.finditer(text):
        if is_ceiling_name(match.group(1)):
            found[f"{path}:{match.group(1)}"] = int(match.group(2).replace("_", ""))
    allowances = _py_allowances(path, text) if path.endswith(".py") else {}
    for match in _LIST_HEAD.finditer(text):
        name = match.group(1)
        body = _strip_comments(text[match.start(2):])
        rows = allowances.get(name) if path.endswith(".py") else int_rows(body)
        if rows:
            found.update({f"{path}:{name}[{row}]": n for row, n in rows.items()})
            found[f"{path}:{name}#entries"] = len(rows)
        elif is_list_name(name) or name in extra:
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
        if path in (UNCOVERED_JSON, THIN_JSON):
            return {f"{prefix}:{name}": int(n) for name, n in doc.items()}
        if path == INFINITE_JSON:
            return {f"{prefix}:{name}": int(n) for name, n in doc["files"].items()}
        if path == CONTRAST_JSON:
            pairs: dict[str, int] = {}
            for theme, failing in doc["themes"].items():
                for pair, ratio in failing.items():
                    pairs[f"{prefix}:{theme}:{pair}"] = 1
                    pairs[f"{prefix}:{theme}:{pair}:ratio"] = -round(float(ratio) * 100)
            return pairs
        rows: dict[str, int] = {}
        for section, files in doc.get("sections", {}).items():
            for name, value in files.items():
                if isinstance(value, dict):
                    rows.update({f"{prefix}:{section}:{name}:{kind}": int(n) for kind, n in value.items()})
                else:
                    rows[f"{prefix}:{section}:{name}"] = int(value)
        return rows
    except (ValueError, AttributeError, TypeError, KeyError) as exc:
        raise GuardError(f"{path} is not a readable known list: {exc}") from exc
