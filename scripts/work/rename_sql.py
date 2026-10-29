
from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path
from typing import Dict, List, Tuple

RENAMES: Dict[str, str] = {name: f"work_{name}" for name in (
    "items", "messages", "reads", "callers", "item_groups", "item_triggers", "item_nudges", "list_prefs", "session_prefs", "inbox",
    "write_actors", "blockers", "item_lineage", "item_waits", "message_receipts", "project_roles", "card_events", "card_rules",
    "card_grants", "card_deals", "card_suggestions", "held_tells")}
RENAMES.update({"meta": "work_meta", "tells": "work_sends", "tell_picks": "work_send_picks"})

_NAMES = "|".join(sorted(RENAMES, key=len, reverse=True))
_KEYWORD = re.compile(
    rf"(?P<kw>\b(?:FROM|INTO|UPDATE|JOIN|TABLE|EXISTS|REFERENCES|ON)\s+)(?P<name>{_NAMES})\b(?![.\w])")
_KEYWORD_QUALIFIED_OK = re.compile(rf"(?P<kw>\b(?:FROM|INTO|UPDATE|JOIN)\s+)(?P<name>{_NAMES})(?=\.)")
_PRAGMA = re.compile(rf"(?P<kw>table_info\(\s*'?)(?P<name>{_NAMES})\b")
_QUALIFIED = re.compile(rf"(?P<kw>(?<![\w.]))(?P<name>{_NAMES})(?=\.(?!(?:py|json|md|db|js|ts|txt)\b)[a-z_]+\b)")
_SQL_WORDS = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|PRAGMA|FROM|JOIN|WHERE|SET|VALUES|AND|OR|IN|ON)\b")


def _rewrite_text(text: str) -> Tuple[str, List[str]]:
    notes: List[str] = []
    if not _SQL_WORDS.search(text):
        return text, notes

    def sub(match: "re.Match[str]") -> str:
        new = RENAMES[match.group("name")]
        notes.append(f"{match.group('name')} -> {new}")
        return match.group("kw") + new

    for pattern in (_KEYWORD, _PRAGMA, _QUALIFIED):
        text = pattern.sub(sub, text)
    return text, notes


def rewrite_source(source: str) -> Tuple[str, List[str]]:
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits: List[Tuple[int, int, str]] = []
    notes: List[str] = []
    previous = tokenize.NEWLINE
    for index, tok in enumerate(tokens):
        if tok.type in (tokenize.COMMENT, tokenize.NL):
            continue
        before, previous = previous, tok.type
        if tok.type not in (tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", -1)):
            continue
        following = next((t.type for t in tokens[index + 1:] if t.type not in (tokenize.COMMENT, tokenize.NL)), tokenize.NEWLINE)
        if tok.type == tokenize.STRING and before in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT) \
                and following in (tokenize.NEWLINE, tokenize.ENDMARKER):
            continue
        start = offsets[tok.start[0] - 1] + tok.start[1]
        end = offsets[tok.end[0] - 1] + tok.end[1]
        original = source[start:end]
        new, found = _rewrite_text(original)
        if found:
            edits.append((start, end, new))
            notes.extend(f"L{tok.start[0]}: {n}" for n in found)
    for start, end, new in reversed(edits):
        source = source[:start] + new + source[end:]
    return source, notes


def main(argv: List[str]) -> int:
    write = "--write" in argv
    targets = [Path(a) for a in argv if a != "--write"]
    files = [p for t in targets for p in ([t] if t.is_file() else sorted(t.rglob("*.py")))]
    for path in files:
        source = path.read_text()
        new, notes = rewrite_source(source)
        if notes:
            print(f"{path}: {len(notes)}")
            for note in notes:
                print(f"  {note}")
            if write:
                path.write_text(new)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
