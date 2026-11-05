from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts.design import raw_controls, raw_values

REPO = Path(__file__).resolve().parents[2]
CLIENT = REPO / "client"
CLIENT_CSS = CLIENT / "css"
FIXTURE = REPO / "tests" / "fixtures" / "design_legacy_known.json"
SECTIONS = ("dialog_frames", "tablists", "css_raw_values", "ts_controls")
_ROLE = re.compile(r"""\brole\b["']?\s*[=,]\s*\\?["']?(dialog|alertdialog|tablist)\b""")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)


def legacy_markup_files(client: Path = CLIENT) -> list[Path]:
    js = sorted((client / "js").rglob("*.js"))
    if not js:
        raise FileNotFoundError(f"no client/js files under {client}")
    html = [p for p in sorted(client.glob("*.html")) if p.name != "style-guide.html"]
    return [*js, *html]


def count_roles(text: str) -> dict[str, int]:
    code = "\n".join(
        ln for ln in _BLOCK_COMMENT.sub("", text).splitlines() if not ln.lstrip().startswith("//")
    )
    roles = _ROLE.findall(code)
    return {"dialog_frames": sum(r != "tablist" for r in roles), "tablists": roles.count("tablist")}


def scan_roles(client: Path = CLIENT, base: Path = REPO) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {"dialog_frames": {}, "tablists": {}}
    for path in legacy_markup_files(client):
        rel = path.relative_to(base).as_posix()
        for kind, n in count_roles(path.read_text(encoding="utf-8")).items():
            if n:
                out[kind][rel] = n
    return out


def scan_css(root: Path = CLIENT_CSS, base: Path = REPO) -> dict[str, dict[str, int]]:
    if not root.is_dir():
        raise FileNotFoundError(f"{root} does not exist")
    return raw_values.scan(root, base)


def scan_all() -> dict[str, dict]:
    roles = scan_roles()
    return {**roles, "css_raw_values": scan_css(), "ts_controls": raw_controls.scan_created_controls()}


def load_known(path: Path = FIXTURE) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))["sections"]


def _flat(section: dict) -> dict[str, int]:
    flat: dict[str, int] = {}
    for rel, value in section.items():
        if isinstance(value, dict):
            flat.update({f"{rel} {kind}": n for kind, n in value.items()})
        else:
            flat[rel] = value
    return flat


def compare(found: dict[str, dict], known: dict[str, dict]) -> tuple[list[str], list[str]]:
    grown: list[str] = []
    stale: list[str] = []
    for name in SECTIONS:
        have, allowed = _flat(found.get(name, {})), _flat(known.get(name, {}))
        for row in sorted(set(have) | set(allowed)):
            if have.get(row, 0) > allowed.get(row, 0):
                grown.append(f"{name} {row}: {have.get(row, 0)} > {allowed.get(row, 0)}")
            elif have.get(row, 0) < allowed.get(row, 0):
                stale.append(f"{name} {row}: {have.get(row, 0)} < {allowed.get(row, 0)}")
    return grown, stale


def lowered(found: dict[str, dict], known: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in SECTIONS:
        today = found.get(name, {})
        section: dict = {}
        for rel, allowed in known.get(name, {}).items():
            if isinstance(allowed, dict):
                kinds = {kind: min(n, (today.get(rel) or {}).get(kind, 0)) for kind, n in allowed.items()}
                kept: dict | int = {kind: n for kind, n in kinds.items() if n > 0}
            else:
                kept = min(allowed, today.get(rel, 0))
            if kept:
                section[rel] = kept
        out[name] = section
    return out


def write_known(lists: dict[str, dict], path: Path = FIXTURE) -> None:
    doc = {
        "about": "legacy listings the top-down gate does not read; may only fall (scripts/design/legacy_listing.py, site review TDC-3)",
        "totals": {name: sum(_flat(lists[name]).values()) for name in SECTIONS},
        "sections": {name: lists[name] for name in SECTIONS},
    }
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    found = scan_all()
    known = load_known(FIXTURE)
    grown, stale = compare(found, known)
    print("totals " + str({name: sum(_flat(found[name]).values()) for name in SECTIONS}))
    for line in grown:
        print("GREW  " + line)
    if "--write" in argv and not grown:
        write_known(lowered(found, known), FIXTURE)
        stale = []
    for line in stale:
        print("LOWER " + line)
    return 1 if grown else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
