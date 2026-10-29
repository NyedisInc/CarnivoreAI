from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB_SRC = REPO / "web" / "src"
BASELINE = REPO / "tests" / "fixtures" / "design_raw_controls_baseline.json"
KINDS = ("buttons", "fields", "checkbox", "radio")
BASE_DIR = "web/src/lib/base/"
NON_FIELD_INPUT_TYPES = frozenset({"range", "color", "file", "hidden", "image"})
PICK_INPUT_TYPES = frozenset({"checkbox", "radio"})
BUTTON_INPUT_TYPES = frozenset({"button", "submit", "reset"})

_BLANK = re.compile(r"<!--.*?-->|<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", re.S)
_OPEN = re.compile(r"<(button|input|select|textarea|svelte:element)(?=[\s/>])")
_TYPE = re.compile(r"""\btype\s*=\s*(?:"([^"]*)"|'([^']*)'|\{\s*["']([^"']*)["']\s*\})""")
_THIS = re.compile(r"""\bthis\s*=\s*(?:"([^"]*)"|'([^']*)'|\{\s*["']([^"']*)["']\s*\})""")
_EXEMPT = re.compile(r"""\bdata-base-exempt\s*=\s*(?:"([^"]+)"|'([^']+)')""")


class ScanError(Exception):
    pass


def blank_nonmarkup(text: str) -> str:
    return _BLANK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def tag_end(text: str, start: int) -> int:
    i, depth, quote = start + 1, 0, ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and depth:
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'`" and (depth or text[i - 1] in "= \n\t"):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
        elif ch == ">" and depth == 0:
            return i + 1
        i += 1
    return len(text)


def _first(match: re.Match[str] | None) -> str | None:
    return next((g for g in match.groups() if g is not None), None) if match else None


def classify(name: str, tag: str) -> str | None:
    if re.search(r"\bdata-base-exempt\b", tag) and _EXEMPT.search(tag):
        return None
    itype = (_first(_TYPE.search(tag)) or "text").lower()
    if name == "svelte:element":
        kind = {"button": "buttons", "input": "fields", "select": "fields", "textarea": "fields"}.get(_first(_THIS.search(tag)) or "")
    elif name == "button" or (name == "input" and itype in BUTTON_INPUT_TYPES):
        kind = "buttons"
    elif name == "input" and itype in PICK_INPUT_TYPES:
        return None if re.search(r"\boc-pick__input\b", tag) else itype
    elif name == "input" and itype in NON_FIELD_INPUT_TYPES:
        kind = None
    else:
        kind = "fields"
    if kind is None:
        return None
    if kind == "buttons":
        return None if re.search(r"\bdata-btn\b|\{\s*\.\.\.buttonAttrs\(", tag) else kind
    return None if re.search(r"\bdata-field\b", tag) else kind


def scan_text(text: str) -> tuple[dict[str, list[int]], list[tuple[int, str]]]:
    clean = blank_nonmarkup(text)
    lines: dict[str, list[int]] = {k: [] for k in KINDS}
    exempt: list[tuple[int, str]] = []
    for m in _OPEN.finditer(clean):
        tag = clean[m.start():tag_end(clean, m.start())]
        line = clean.count("\n", 0, m.start()) + 1
        reason = _first(_EXEMPT.search(tag))
        if reason:
            exempt.append((line, reason))
        kind = classify(m.group(1), tag)
        if kind:
            lines[kind].append(line)
    return lines, exempt


def is_scanned(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (rel.endswith(".svelte") and not rel.startswith(BASE_DIR) and ".test." not in name
            and "/__tests__/" not in rel and "node_modules" not in rel)


def scan_detail(root: Path = WEB_SRC, base: Path = REPO) -> tuple[dict[str, dict[str, list[int]]], dict[str, list[tuple[int, str]]]]:
    if not root.is_dir():
        raise ScanError(f"scan root {root} does not exist")
    raw: dict[str, dict[str, list[int]]] = {}
    exempt: dict[str, list[tuple[int, str]]] = {}
    seen = 0
    for path in sorted(root.rglob("*.svelte")):
        rel = path.relative_to(base).as_posix()
        if not is_scanned(rel):
            continue
        seen += 1
        lines, ex = scan_text(path.read_text(encoding="utf-8"))
        if any(lines.values()):
            raw[rel] = {k: v for k, v in lines.items() if v}
        if ex:
            exempt[rel] = ex
    if not seen:
        raise ScanError(f"no scannable .svelte file under {root}")
    return raw, exempt


def scan(root: Path = WEB_SRC, base: Path = REPO) -> dict[str, dict[str, int]]:
    return {rel: {k: len(v) for k, v in kinds.items()} for rel, kinds in scan_detail(root, base)[0].items()}


def load_baseline(path: Path = BASELINE) -> dict[str, dict[str, int]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError) as exc:
        raise ScanError(f"{path} is not a readable baseline: {exc}") from exc


def compare(found: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]],
            lines: dict[str, dict[str, list[int]]] | None = None) -> tuple[list[str], list[str]]:
    grown: list[str] = []
    stale: list[str] = []
    for rel in sorted(set(found) | set(baseline)):
        for kind in KINDS:
            have, allowed = found.get(rel, {}).get(kind, 0), baseline.get(rel, {}).get(kind, 0)
            if have > allowed:
                where = f" (lines {', '.join(map(str, lines[rel][kind]))})" if lines and rel in lines else ""
                grown.append(f"{rel} {kind}: {have} > {allowed}{where}")
            elif have < allowed:
                stale.append(f"{rel} {kind}: {have} < {allowed}")
    return grown, stale


def totals(found: dict[str, dict[str, int]]) -> dict[str, int]:
    return {k: sum(c.get(k, 0) for c in found.values()) for k in KINDS}


def write_baseline(found: dict[str, dict[str, int]], path: Path = BASELINE) -> None:
    doc = {"about": "hand-written buttons and fields outside web/src/lib/base per web/src file; may only fall "
                    "(scripts/design/raw_controls.py, issue #2361)", "totals": totals(found), "files": found}
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    try:
        raw, exempt = scan_detail(WEB_SRC, REPO)
        found = {rel: {k: len(v) for k, v in kinds.items()} for rel, kinds in raw.items()}
        if "--write" in argv:
            write_baseline(found)
        grown, stale = compare(found, load_baseline(), raw)
    except ScanError as exc:
        print(f"raw_controls: CANNOT SCAN - {exc}", file=sys.stderr)
        return 2
    print(f"files with raw controls: {len(found)}; totals {totals(found)}; named exemptions {sum(map(len, exempt.values()))}")
    if "--lines" in argv:
        for rel, kinds in raw.items():
            for kind, nums in kinds.items():
                print(f"{rel} {kind}: {', '.join(map(str, nums))}")
    for line in grown:
        print("GREW  " + line)
    for line in stale:
        print("LOWER " + line)
    return 1 if grown else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
